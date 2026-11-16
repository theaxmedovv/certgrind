import asyncio
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async as db
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from rooms.models import Room

from . import events, powerups, services
from .services import GameError

log = logging.getLogger(__name__)


class StudentConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        qs = parse_qs(self.scope["query_string"].decode())
        token = (qs.get("t") or [None])[0]
        cookie = self.scope.get("cookies", {}).get("pt")
        p = await db(services.get_participant_by_token)(token) if token else None
        # token + cookie ikkalasi mos kelishi shart: boshqa brauzerdan kirib bo'lmaydi
        if not p or cookie != token:
            await self.close(code=4403)
            return
        self.pid, self.rid = p.id, p.room_id
        self.groups_joined = [events.students_group(self.rid), events.participant_group(self.pid)]
        for g in self.groups_joined:
            await self.channel_layer.group_add(g, self.channel_name)
        await self.accept()
        # xuddi shu o'quvchining eski ulanishlarini yopish
        await self.channel_layer.group_send(
            events.participant_group(self.pid), {"type": "ws.replaced", "new": self.channel_name}
        )
        await self.send_state()

    async def disconnect(self, code):
        for g in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(g, self.channel_name)

    # --- guruh hodisalari
    async def ws_send(self, event):
        await self.send_json(event["payload"])

    async def ws_refresh(self, event):
        await self.send_state()

    async def ws_replaced(self, event):
        if event["new"] != self.channel_name:
            await self.send_json({"t": "replaced"})
            await self.close(code=4409)

    async def send_state(self):
        try:
            await self.send_json(await db(services.student_state)(self.pid))
        except Exception:
            log.exception("state xatosi")

    # --- mijozdan kelgan xabarlar
    async def receive_json(self, content, **kwargs):
        t = content.get("t")
        uuid = content.get("uuid")
        try:
            if t == "sync":
                await self.send_state()
            elif t == "begin":
                await db(services.begin_participant)(self.pid)
                await self.send_state()
            elif t == "next":
                await self.send_json(await db(services.serve_question)(self.pid))
            elif t == "answer":
                res = await db(services.submit_answer)(
                    self.pid, content.get("position"), content.get("option_id"), uuid
                )
                await self.send_json(res)
            elif t == "violation":
                await db(services.report_violation)(self.pid, content.get("type"))
            elif t == "powerup":
                # nishonni SERVER tanlaydi; mijoz faqat kod va turini yuboradi
                res = await db(powerups.use_powerup)(self.pid, content.get("code"), content.get("kind"))
                await self.send_json(res)
            elif t == "ping":
                await self.send_json(await db(services.time_sync)(self.pid))
        except GameError as e:
            await self.send_json({"t": "error", "code": e.code, "message": e.message, "uuid": uuid})
            await self.send_state()
        except Exception:
            log.exception("StudentConsumer xatosi")
            await self.send_json(
                {"t": "error", "code": "server", "message": "Server xatosi", "uuid": uuid}
            )


def _owns_room(user, room_id):
    return user.is_superuser or Room.objects.filter(pk=room_id, teacher=user).exists()


def _check_clock(room_id):
    """Vaqti tugagan xonani yakunlaydi (Celery ishlamagan holat uchun zaxira)."""
    room = Room.objects.filter(pk=room_id).first()
    if room and room.status == Room.Status.RUNNING:
        services.refresh_room_clock(room)


async def _clock_loop(room_id, period=3):
    try:
        while True:
            await asyncio.sleep(period)
            try:
                await db(_check_clock)(room_id)
            except Exception:
                log.exception("clock loop xatosi")
    except asyncio.CancelledError:
        pass


class TeacherConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        self.rid = int(self.scope["url_route"]["kwargs"]["room_id"])
        ok = False
        if user and user.is_authenticated:
            ok = await db(_owns_room)(user, self.rid)
        if not ok:
            await self.close(code=4403)
            return
        self.group = events.teacher_group(self.rid)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_snapshot()
        self._clock = asyncio.ensure_future(_clock_loop(self.rid))

    async def disconnect(self, code):
        if getattr(self, "_clock", None):
            self._clock.cancel()
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def ws_send(self, event):
        await self.send_json(event["payload"])

    async def send_snapshot(self):
        from . import snapshots

        def build():
            room = services.refresh_room_clock(Room.objects.get(pk=self.rid))
            return snapshots.teacher_snapshot(room)

        await self.send_json(await db(build)())

    async def receive_json(self, content, **kwargs):
        t = content.get("t")
        rid = self.rid
        try:
            if t == "snapshot":
                await self.send_snapshot()
            elif t == "start":
                await db(services.start_room)(rid)
            elif t == "pause":
                await db(services.pause_room)(rid)
            elif t == "resume":
                await db(services.resume_room)(rid)
            elif t == "add_time":
                await db(services.add_time)(rid, int(float(content.get("minutes", 0)) * 60))
            elif t == "finish":
                await db(services.finish_room)(rid, True)
            elif t == "kick":
                await db(services.kick_participant)(rid, content.get("pid"))
            elif t == "violation":
                await db(services.decide_violation)(rid, content.get("id"), content.get("decision"))
            elif t == "late":
                await db(services.decide_late)(
                    rid, content.get("pid"), bool(content.get("allow")), content.get("extra", 0)
                )
            elif t == "extra_time":
                await db(services.give_extra_time)(rid, content.get("pid"), content.get("seconds"))
            elif t == "results_visible":
                await db(services.set_results_visible)(rid, content.get("value"))
        except GameError as e:
            await self.send_json({"t": "error", "message": e.message})
        except (TypeError, ValueError):
            await self.send_json({"t": "error", "message": "Noto'g'ri qiymat"})
        except Exception:
            log.exception("TeacherConsumer xatosi")
            await self.send_json({"t": "error", "message": "Server xatosi"})


class ProjectorConsumer(AsyncJsonWebsocketConsumer):
    """Proyektor ekrani: faqat o'qish. QR/kirganlar, Top 10, super-kuch lentasi, podium."""

    async def connect(self):
        user = self.scope.get("user")
        self.rid = int(self.scope["url_route"]["kwargs"]["room_id"])
        ok = bool(user and user.is_authenticated and await db(_owns_room)(user, self.rid))
        if not ok:
            await self.close(code=4403)
            return
        self.group = events.projector_group(self.rid)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_snapshot()
        self._clock = asyncio.ensure_future(_clock_loop(self.rid))

    async def disconnect(self, code):
        if getattr(self, "_clock", None):
            self._clock.cancel()
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def ws_send(self, event):
        await self.send_json(event["payload"])

    async def send_snapshot(self):
        from . import snapshots

        def build():
            room = services.refresh_room_clock(Room.objects.get(pk=self.rid))
            return snapshots.projector_snapshot(room)

        await self.send_json(await db(build)())

    async def receive_json(self, content, **kwargs):
        # boshqaruv buyruqlari qabul qilinmaydi; faqat yangilash so'rovi
        if content.get("t") == "snapshot":
            await self.send_snapshot()
