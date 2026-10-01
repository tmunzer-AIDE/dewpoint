"""Throwaway: a scheduler with ~21,600 queued loop steps (240 siblings in 10 x 10), for timing snapshot and restore."""
import json, random, time
import s_defer as S
from dewpoint.engine.runtime.scheduler import Scheduler
from tests.engine.runtime.support import program


def big() -> Scheduler:
    prog = program(S.body_siblings(240))
    s = Scheduler(prog); s.start()
    rng = random.Random(7); running = []; collects = []
    for turn in range(200000):
        s.take_cancels(); running += s.take_ready(); collects += s.take_collects(); s.take_settled()
        if len(s._deferred) > 21000 and turn % 50 == 0:
            while running or collects:
                if collects:
                    c = collects.pop(); s.collected(c.loop, c.index, c.index)
                else:
                    inst = running.pop(); st = s.step(inst)
                    if st.ref == S.LOOP:
                        s.consume_capture(inst); s.open_loop(inst, list(st.config["items"]), concurrency=int(st.config["concurrency"]), stop_on_error=False)
                    else: s.succeed(inst, {"n": 1})
                s.take_settled(); s.take_cancels()
            break
        loops = [n for n, r in enumerate(running) if s.step(r).ref == S.LOOP]
        pick = loops[0] if loops else (len(running) if collects else rng.randrange(len(running)))
        if pick >= len(running):
            c = collects.pop(pick - len(running)); s.collected(c.loop, c.index, c.index); continue
        inst = running.pop(pick); st = s.step(inst)
        if st.ref == S.LOOP:
            s.consume_capture(inst); s.open_loop(inst, list(st.config["items"]), concurrency=int(st.config["concurrency"]), stop_on_error=False)
        else: s.succeed(inst, {"n": 1})
    s.take_settled()
    return s


def parts(gen):
    out, last = [], time.perf_counter()
    while True:
        try:
            u = next(gen); now = time.perf_counter(); out.append((u, round((now - last) * 1000, 2))); last = now
        except StopIteration as d:
            return d.value, out
