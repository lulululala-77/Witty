# -*- coding: utf-8 -*-
"""父进程：只管界面。截图 + OCR 在 app/worker.py 的子进程里跑，队列里收新消息 →
冒出新的对方消息才调 engine → 悬浮窗给 3 条候选 → 人点「填入」。发送永远手动。静默期零调用。
上下文、结果、聊天记录都按会话名（子进程 OCR 头部标题得来）分开存，切会话不串味。

    pip install rapidocr-onnxruntime numpy windows-capture PySide6-Fluent-Widgets
两个模型（判断 Jev / 起草语言模型）的来源和 key 在独立设置页填写，不用改代码。IDE 里直接 Run。
"""
import multiprocessing
import os
import json
import queue
import threading
import traceback
import time
import uuid
from app import analytics
from datetime import datetime, timedelta
from collections import deque

from app import settings, update, worker
from app.capture import find_chat_hwnd
from app.fill import fill
from app.overlay import Overlay
from app.version import VERSION
from core.engine import analyze
from core.rag import retrieve, add_memory, log_trace
from core import llm, providers
from core.memory_write_prompt import SYSTEM_PROMPT as MEMORY_WRITE_SYSTEM_PROMPT
from core.memory_input import build_memory_input, format_memory_messages, has_group_speakers
from core.jev_client import _api_key
from app.i18n import T

# {会话名: {history, result, rev, target, senders}}：每个会话各自的上下文、上次结果和版本号，互不串味
# history 里是 [(who, text, name)]，engine 只认 her/me；群聊其他成员归为 her，name 保存具体发言人；
# 只是缓冲区；回复模型实际喂几条由「参考上下文」决定，记忆判断按 10 条新消息批次触发
# senders：这个群里发过言的人，去重、最近的排最前；target：用户挑的回复对象（None = 跟着最近那个走）
chats = {}
state = {"area": None, "busy": False, "rerun": None, "hwnd": None, "chat": ""}
rag_enabled = True
pending_rag_trace = ""
results = queue.Queue()
update_result = queue.Queue()  # 独立小队列，别跟 results 的 (kind, r, title, revision) 形状搅在一起


def chat_of(title):
    return chats.setdefault(title, {"history": deque(maxlen=60), "result": None, "rev": 0,
                                    "target": None, "senders": [], "pending_memory": [],
                                    # Wall-clock time of the latest newly observed
                                    # Parsed Message; used for the 3-minute batch flush.
                                    "last_memory_at": 0.0, "memory_busy": False})


def auto_memory_text(chat):
    """未处理的新消息 + 它之前最近十条上下文。"""
    pending = list(chat.get("pending_memory", []))
    if not pending:
        return ""
    history = list(chat["history"])
    first = max(0, len(history) - len(pending) - 10)
    context = history[first:len(history)]
    return format_memory_messages(context, is_group=has_group_speakers(chat))


def trigger_auto_memory(title, force=False):
    chat = chat_of(title)
    pending = chat.get("pending_memory", [])
    if not pending or chat.get("memory_busy"):
        return
    # Memory judging is batched by all new conversation messages.
    if not force and len(pending) < 10:
        return
    text = auto_memory_text(chat)
    chat["memory_busy"] = True

    def run():
        try:
            result = save_memory(title, text)
            if not str(result).startswith("模型总结失败"):
                # Only acknowledge the batch after a valid model response.
                chat["pending_memory"] = []
                chat["last_memory_at"] = 0.0
        finally:
            chat["memory_busy"] = False
    threading.Thread(target=run, daemon=True).start()


def target_of(title):
    """这个会话现在的回复对象：用户挑过且人还在就用它，否则用最近说话的那个；单聊没有发言人 → None。"""
    chat = chat_of(title)
    if chat["target"] in chat["senders"]:
        return chat["target"]
    return chat["senders"][0] if chat["senders"] else None


def fill_reply(text):
    if state["hwnd"] is None:  # 子进程重开过，hwnd 可能换了，用最新的
        raise RuntimeError(T("未找到聊天窗口，请确认已经打开"))
    if state["area"] is None:
        raise RuntimeError(T("输入区域尚不可用，请确认聊天窗口可见（不要最小化）"))
    if settings.reply_target() and ov.at_prefix_enabled():
        target = target_of(ov.current_chat())  # 填进去的是界面上正看着的那个会话的对象
        if target:
            text = f"@{target} " + text  # 纯文本，微信不认成真正的 @，只是让群里看得出在跟谁说
    fill(state["hwnd"], state["area"], text)


def spawn_worker():
    """开一个采集子进程，它跟着 capture_on 走：置位=采集，清掉=暂停。"""
    p = multiprocessing.Process(target=worker.run,
                                args=(q, state["hwnd"], capture_on, debug_on, state.get("app")),
                                daemon=True)
    p.start()
    return p


def set_debug(on):
    """调试视图开关：开 → 开窗 + 置位（子进程这才开始送帧，一帧 2~3MB）；关 → 清掉 + 收窗。"""
    global dbg
    if not on:
        debug_on.clear()
        if dbg is not None:
            dbg.hide()
        return
    if dbg is None:
        from app.debugwin import DebugWindow

        dbg = DebugWindow(on_close=on_debug_closed)
    dbg.show()
    debug_on.set()


def on_debug_closed():
    """用户直接关了调试窗 = 把开关也关了，否则设置页显示开着但没窗。"""
    debug_on.clear()
    ov.set_debug_switch(False)
    settings.save(debug_view_on=False)


def on_language_changed():
    """主界面切换语言后，同步刷新已经打开过的调试窗。"""
    if dbg is not None:
        dbg.retranslate()


def on_toggle_capture(on):
    """标题栏开关。启动时没找到微信就没有子进程，这会儿再找一次，找到了才真开得起来。"""
    global child
    if not on:
        capture_on.clear()
        return
    if child is None:
        try:
            state["hwnd"], found = find_chat_hwnd()
            state["app"] = found.key
        except RuntimeError:
            ov.set_capture(False, "未找到聊天窗口，打开后再开启采集")
            return
        child = spawn_worker()
    capture_on.set()


def analyze_bg(msgs, title, revision, reply_to=None):
    """后台线程只跑网络调用，结果丢队列；UI 只在主线程的 tick 里动（Qt 不能跨线程碰）。"""
    telemetry_id = str(uuid.uuid4())
    started = time.monotonic()
    analytics.track('generation_started', suggestion_id=telemetry_id)
    try:
        latest = msgs[-1][1] if msgs else ""
        query_speaker = None
        if msgs:
            if msgs[-1][0] == "me":
                query_speaker = "用户本人"
            elif len(msgs[-1]) > 2 and msgs[-1][2]:
                query_speaker = msgs[-1][2]
            elif not has_group_speakers(chat_of(title)):
                query_speaker = title
        use_rag = rag_enabled and os.environ.get("JEV_RAG_ENABLED", "1").lower() not in {"0", "false", "off"}
        other_memory = retrieve(latest, dimension="other_person", contact=title, limit=5, query_speaker=query_speaker) if use_rag else ""
        scenario_memory = retrieve(latest, dimension="scenario", limit=3, query_speaker=query_speaker) if use_rag else ""
        user_memory = retrieve(latest, dimension="user_preference", limit=5, query_speaker=query_speaker) if use_rag else ""
        global pending_rag_trace
        judge_context = "\n".join(x for x in (other_memory, scenario_memory) if x)
        draft_context = "\n".join(x for x in (other_memory, user_memory, scenario_memory) if x)
        pending_rag_trace = f"当前会话：{title}\n最新消息：{latest}\n\n给 Jev：\n{judge_context or '（空）'}\n\n给 DeepSeek：\n{draft_context or '（空）'}"
        result = analyze(msgs, settings.relationship(), context=settings.context(),
                                   model=settings.draft_model() or None,
                                   provider=settings.draft_provider(),
                                   base_url=settings.draft_base_url() or None,
                                   reply_to=reply_to, style=settings.style(),
                                   thinking=settings.thinking(),
                                   jev_provider=settings.jev_provider(),
                                   jev_model=settings.jev_model() or None,
                                   judge_memory=judge_context,
                                   draft_memory=draft_context)
        if not result.get('candidates'):
            raise ValueError('empty candidates')
        result['_analytics_id'] = telemetry_id
        result['_analytics_started'] = started
        log_trace(title, latest, judge_context, draft_context, result)
        analytics.track('generation_finished', suggestion_id=telemetry_id, status='success',
                        candidate_count=len(result['candidates']), duration_ms=round((time.monotonic()-started)*1000))
        results.put(("ok", result, title, revision))
    except Exception as e:
        analytics.track('generation_finished', suggestion_id=telemetry_id, status='failure',
                        duration_ms=round((time.monotonic()-started)*1000))
        results.put(("err", f"{T('分析失败: ')}{e}", title, revision))


def save_memory(contact, text, commit=False):
    spec = providers.DRAFT_PROVIDERS[settings.draft_provider()]
    prompt = build_memory_input(contact, text, is_group=has_group_speakers(chat_of(contact)))
    try:
        raw = llm.chat(spec.protocol, settings.draft_base_url() or spec.base,
                       _api_key(providers.LLM_ENV), settings.draft_model() or spec.default,
                       MEMORY_WRITE_SYSTEM_PROMPT,
                       [prompt], max_tokens=400, extra_body=spec.extra(False), headers=spec.headers)
        data = json.loads(raw[raw.find('{'):raw.rfind('}') + 1])
        if not data.get("save"):
            return "模型判断：不保存到 RAG（这段内容不够稳定或长期有用）。"
        summary = str(data.get("summary", "")).strip()
        if not summary:
            return "模型判断：未生成有效记忆，不保存到 RAG。"
        category = data.get("category") or "event"
        if category not in {"event", "fact", "state", "boundary", "preference"}:
            category = "event"
        try:
            importance = max(1, min(5, int(data.get("importance", 3))))
        except (TypeError, ValueError):
            importance = 3
        default_retention = {
            "event": "recent",
            "state": "recent",
            "fact": "long_term",
            "preference": "long_term",
            "boundary": "long_term",
        }
        retention = data.get("retention") or default_retention.get(category, "recent")
        if retention not in {"today", "recent", "long_term"}:
            retention = default_retention.get(category, "recent")
        event_date = str(data.get("event_date") or "").strip()
        try:
            event_day = datetime.strptime(event_date, "%Y-%m-%d").date() if event_date else datetime.now().date()
        except ValueError:
            event_date = ""
            event_day = datetime.now().date()
        today = datetime.now().date()
        age_days = (today - event_day).days
        # Enforce the semantic boundary even when the model chooses an inconsistent label.
        if retention == "today" and age_days != 0:
            retention = "recent" if 0 <= age_days <= 7 else "long_term"
        if retention == "recent" and not (0 <= age_days <= 7):
            retention = "long_term"
        days = {"today": 7, "recent": 30}.get(retention)
        expires_at = (datetime.combine(event_day, datetime.min.time()) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days else None
        add_memory(summary, "other_person", contact=contact, category=category,
                   importance=importance, expires_at=expires_at, event_date=event_date or None)
        expiry_text = f"，{days}天后过期" if days else "，不过期"
        return f"模型已自动保存到 RAG（{category}，重要性 {importance}/5{expiry_text}）：\n{summary}"
    except Exception as exc:
        return f"模型总结失败：{exc}\n\n{text}"


def toggle_rag(enabled):
    global rag_enabled
    rag_enabled = bool(enabled)


def check_update_bg():
    """启动时后台查一次新版本，跟 analyze_bg 一个套路：网络调用在线程里，UI 只在 tick() 里动。"""
    r = update.check_latest(VERSION)
    if r:
        update_result.put(r)


def start_analyze(title, msgs):
    if not settings.has_jev_key():
        ov.set_status("请先在设置中配置模型", "warning")
        return
    if not settings.has_llm_key():
        ov.set_status(lambda name=settings.draft_provider_name():
                      f"{T('起草来源 ')}{name}{T(' 没填密钥，去设置里补上')}", "warning")
        return
    state["busy"] = True
    # analyze() receives the latest `context` messages, or fewer if the
    # session has not accumulated that many yet.
    ov.set_context_stats(min(len(msgs), settings.context()), settings.context())
    ov.set_busy(True)
    reply_to = target_of(title) if settings.reply_target() else None  # 开关关着就是今天的行为
    threading.Thread(target=analyze_bg, args=(msgs, title, chat_of(title)["rev"], reply_to),
                     daemon=True).start()


def on_target_change(title, name):
    """用户挑了回复对象：记下来，这个会话里有对方的话就照新对象重跑一次。"""
    chat = chat_of(title)
    chat["target"] = name
    msgs = list(chat["history"])
    if not any(m[0] == "her" for m in msgs):
        return
    if state["busy"]:
        state["rerun"] = (title, msgs)
        ov.set_busy(True)
    else:
        start_analyze(title, msgs)


def drain():
    """把子进程队列里攒的东西全收掉。"""
    global child
    while True:
        try:
            msg = q.get_nowait()
        except queue.Empty:
            return
        kind = msg[0]
        if kind == "area":  # 只是窗口挪了位置，坐标跟着更新，别的什么都不用动
            state["area"] = msg[1]
            continue
        if kind == "chat":  # 微信切了会话，界面跟过去（用户正浏览别的会话时也跟，微信是准的）
            state["chat"] = msg[1]
            ov.set_chat(msg[1])
            continue
        if kind == "debug":  # 调试视图的一帧；窗口不在就直接丢掉
            if dbg is not None:
                dbg.show_packet(msg[1])
            continue
        if kind == "status":  # 单帧识别失败/报错，提示一下就好，别把正在跑的分析和已知坐标清掉
            ov.set_status(msg[1], "warning")
            ov.log(msg[1])
            continue
        if kind == "paused":  # 子进程确认已暂停
            ov.set_capture(False)
            continue
        if kind == "resumed":  # 子进程重新开始采集
            ov.set_capture(True)
            continue
        if kind == "dead":  # 采集彻底停了（微信关了之类），这才是真的要清状态
            state["area"] = None
            for c in chats.values():  # 在跑的分析作废，回来的结果不再往界面上贴
                c["rev"] += 1
            state["rerun"] = None
            ov.invalidate_replies()
            ov.set_busy(False)
            ov.set_capture(False, msg[1])
            ov.log(msg[1])
            if child is not None:  # 子进程已经不干活了，收掉引用，下次打开开关重开一个
                child.terminate()
                child.join()
                child = None
            continue
        _, title, new, area = msg
        state["area"] = area
        chat = chat_of(title)
        chat["rev"] += 1  # 这个会话有新消息了，它在跑的分析作废
        if title == ov.current_chat():  # 看的是别的会话就别把人家的候选划掉
            ov.invalidate_replies()
        for who, name, text in new:
            chat["history"].append((who, text, name))
            if who in {"her", "me"}:
                chat.setdefault("pending_memory", []).append((who, text, name))
                chat["pending_memory"] = chat["pending_memory"][-20:]
                # The inactivity timer is reset by every newly observed
                # message, including the user's own replies. This means the
                # batch is flushed only after the conversation has actually
                # gone quiet for three minutes.
                chat["last_memory_at"] = time.time()
            ov.log_message(who, text, name, chat=title)
            if who == "her" and name:  # 群里发过言的人，去重后最近的排最前
                if name in chat["senders"]:
                    chat["senders"].remove(name)
                chat["senders"].insert(0, name)
        ov.set_targets(title, chat["senders"], target_of(title))  # 显不显示这一行由悬浮窗按开关决定
        if new[-1][0] == "her":  # 只有对方最新说话才值得分析
            msgs = list(chat["history"])
            if state["busy"]:
                state["rerun"] = (title, msgs)
                ov.set_busy(True)
            else:
                start_analyze(title, msgs)
        else:
            state["rerun"] = None
            ov.set_busy(False)
            ov.set_status("你已回复，等待对方的新消息")
        trigger_auto_memory(title)


def tick():
    global pending_rag_trace
    if pending_rag_trace:
        ov._last_rag_trace = pending_rag_trace
        pending_rag_trace = ""
    try:
        drain()
        now = time.time()
        for title, chat in list(chats.items()):
            last = chat.get("last_memory_at", 0.0)
            if last and now - last >= 180:
                trigger_auto_memory(title, force=True)
        while not update_result.empty():
            latest, url = update_result.get()
            ov.set_update(latest, url)
        while not results.empty():
            kind, r, title, revision = results.get()
            state["busy"] = False
            if state["rerun"]:  # 分析期间又来了新消息，接着跑最新的
                if kind == 'ok':
                    analytics.track('result_discarded', suggestion_id=r.get('_analytics_id', ''), reason='new_message_pending')
                (t, msgs), state["rerun"] = state["rerun"], None
                start_analyze(t, msgs)
                continue
            if revision != chat_of(title)["rev"]:  # 这个会话后来又说话了，这份结果过期了
                if kind == 'ok':
                    analytics.track('result_discarded', suggestion_id=r.get('_analytics_id', ''), reason='stale_revision')
                ov.set_busy(False)
                continue
            if kind == "ok":
                chat_of(title)["result"] = r  # 先存着；正看着这个会话才立刻贴上去
                if title == ov.current_chat():
                    ov.show(r)
                else:
                    ov.set_busy(False)
            else:
                ov.set_busy(False)
                ov.set_status("生成失败，请检查网络和服务设置；新消息到来后会重试。", "error")
                ov.log(r)
    except Exception:
        traceback.print_exc()  # 一帧出错不退出
    ov.after(50, tick)


if __name__ == "__main__":  # Windows 的 spawn 会让子进程重新执行本文件，没这行就无限套娃开进程
    multiprocessing.freeze_support()  # 打包成 exe 后 spawn 出来的子进程会重跑一遍 exe，没这行就无限弹界面
    analytics.initialize()
    # Qt 6 already sets Per-Monitor-V2 DPI awareness. Calling the legacy
    # SetProcessDPIAware here conflicts with Qt and produces a harmless but
    # noisy "SetProcessDpiAwarenessContext failed" warning on Windows.
    q = multiprocessing.Queue()
    capture_on = multiprocessing.Event()  # 父子进程共用的开关，置位=采集
    debug_on = multiprocessing.Event()  # 同上，置位=子进程往队列里送整帧给调试窗
    child = dbg = None
    ov = Overlay(on_fill=fill_reply, on_toggle_capture=on_toggle_capture,
                 on_target_change=on_target_change, on_toggle_debug=set_debug,
                 on_language_changed=on_language_changed,
                 on_save_memory=save_memory,
                 on_toggle_rag=toggle_rag,
                 result_of=lambda t: chats.get(t, {}).get("result"))
    try:
        state["hwnd"], found = find_chat_hwnd()
        state["app"] = found.key
    except RuntimeError:
        ov.set_capture(False, "未找到聊天窗口，打开后再开启采集")
    else:
        capture_on.set()
        child = spawn_worker()
    if settings.debug_view():  # 上次开着就直接开回来
        set_debug(True)
    if not settings.has_jev_key():
        ov.set_status("请先在设置中配置模型", "warning")
        ov.after(0, ov.open_settings)
    if settings.check_update() and update.parse_version(VERSION):  # 开发版没有版本号，不查也不烦源码用户
        threading.Thread(target=check_update_bg, daemon=True).start()
    ov.after(50, tick)
    try:
        ov.run()
    finally:
        analytics.shutdown()
        if child is not None:
            child.terminate()
