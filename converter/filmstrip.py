"""A native-drop photo contact strip and background-safe NEF preview reader."""
from collections import deque
from datetime import datetime
from io import BytesIO
from pathlib import Path
from secrets import randbelow
import math
import time
import tkinter as tk

import rawpy
from PIL import Image, ImageTk
from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP
from tkinter import font as tkfont

from retro_ui import CARD, PAPER, INK, MUTED, LINE, ACCENT, FILM

STATE_LABELS = {'waiting': '待转换', 'processing': '转换中', 'complete': '完成',
                'complete-warning': '完成·有提示', 'failed': '失败'}


def load_thumbnail(path, size=(188, 128)):
    """Read only the embedded preview when available; never write to the NEF."""
    with rawpy.imread(str(path)) as raw:
        flip = raw.sizes.flip
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                with Image.open(BytesIO(thumb.data)) as embedded:
                    image = embedded.convert('RGB')
            else:
                image = Image.fromarray(thumb.data).convert('RGB')
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            image = Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True,
                                                    output_bps=8, user_flip=0))
        # Some camera JPEGs show the whole sensor despite an in-camera crop.
        s = raw.sizes
        if s.width and s.height and abs(image.width / image.height - s.width / s.height) < .04:
            left, top = s.crop_left_margin - s.left_margin, s.crop_top_margin - s.top_margin
            w, h = s.crop_width, s.crop_height
            if 0 <= left < s.width and 0 <= top < s.height and w > 0 and h > 0 and left + w <= s.width and top + h <= s.height:
                image = image.crop((round(left * image.width / s.width), round(top * image.height / s.height),
                                    round((left + w) * image.width / s.width), round((top + h) * image.height / s.height)))
        rotation = {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90,
                    6: Image.Transpose.ROTATE_270}.get(flip)
        if rotation is not None:
            image = image.transpose(rotation)
        image.thumbnail(size, Image.Resampling.LANCZOS)
        return image.copy()


class FilmStrip(tk.Canvas):
    SLOT = 300
    IMAGE = (284, 190)
    BASE = '#111310'
    EDGE = '#d5a777'

    def __init__(self, master, fonts, add, detail, selection_changed=None, remove=None):
        super().__init__(master, bg=PAPER, bd=0, highlightthickness=0,
                         height=288, takefocus=True, xscrollincrement=1)
        self.fonts, self.add, self.detail = fonts, add, detail
        self.selection_changed = selection_changed or (lambda: None)
        self.remove_selected = remove or (lambda: None)
        self.context_menu = tk.Menu(self, tearoff=False, bg=CARD, fg=PAPER,
                                    activebackground='#535d4c', activeforeground=PAPER)
        self.edge_font = tkfont.Font(self, family=fonts['mono'], size=10)
        self.number_font = tkfont.Font(self, family=fonts['mono'], size=11)
        self.label_number = f'{randbelow(1000000):06}'
        self.label_date = datetime.now().strftime('%Y.%m.%d')
        self.records, self.selected, self.anchor = {}, set(), None
        self.order = []
        self.pending = deque()
        self.animation = None
        self.animation_job = None
        self.locked = self.drag_over = False
        self._redraw_job = None
        self._motion_job = self._motion_target = None
        self.following = False
        self._follow_fraction = 0.
        self._wheel_remainder = 0.
        self.bind('<Configure>', self.redraw)
        self.bind('<Button-1>', self._select)
        self.bind('<Double-Button-1>', self._detail)
        self.bind('<Button-2>' if sys_platform_mac() else '<Button-3>', self._remove_context)
        if sys_platform_mac():
            self.bind('<Control-Button-1>', self._remove_context)
        self.bind('<MouseWheel>', self._wheel)
        self.bind('<Shift-MouseWheel>', self._wheel)
        try:
            self.bind('<TouchpadScroll>', self._touchpad)
            self.bind('<Shift-TouchpadScroll>', self._touchpad)
        except tk.TclError:  # Tk 8.6 has no separate high-resolution event.
            pass
        self.bind('<Button-4>', lambda e: self._scroll_pixels(-48))
        self.bind('<Button-5>', lambda e: self._scroll_pixels(48))
        if self.tk.call('tk', 'windowingsystem') == 'x11':
            self.bind('<Button-6>', lambda e: self._scroll_pixels(-48))
            self.bind('<Button-7>', lambda e: self._scroll_pixels(48))
        for key, delta in [('Left', -1), ('Right', 1)]:
            self.bind('<'+key+'>', lambda e, d=delta: self._move(d, e))
        self.bind('<Return>', self._detail)
        self.bind('<space>', self._detail)
        for modifier in ('Command', 'Control'):
            self.bind(f'<{modifier}-a>', self._all)
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<DropEnter>>', self._drag_enter)
        self.dnd_bind('<<DropPosition>>', self._drag_enter)
        self.dnd_bind('<<DropLeave>>', self._drag_leave)
        self.dnd_bind('<<Drop>>', self._drop)

    def _drag_enter(self, event):
        if self.locked:
            return REFUSE_DROP
        if not self.drag_over:
            self.drag_over = True
            self.redraw()
        return COPY

    def _drag_leave(self, event=None):
        self.drag_over = False
        self.redraw()

    def _drop(self, event):
        self._drag_leave()
        if self.locked:
            return REFUSE_DROP
        paths = self.tk.splitlist(event.data)
        return COPY if self.add(paths) else REFUSE_DROP

    def append(self, path, token):
        key = str(path)
        self.order.append(key)
        self.records[key] = {'path': Path(path), 'token': token, 'photo': None, 'image': None,
                             'preview': None, 'draw_height': None,
                             'state': 'waiting', 'preview_error': False}
        self.redraw()

    def remove(self, keys):
        self.end_follow()
        self._cancel_motion()
        for key in keys:
            self.records.pop(key, None)
            self.selected.discard(key)
        self.order = [key for key in self.order if key in self.records]
        self.redraw()

    def selection(self):
        return [key for key in self.order if key in self.selected]

    def set_state(self, key, state):
        if key in self.records:
            self.records[key]['state'] = state
            self.redraw()

    def reveal(self, key):
        if key not in self.records:
            return
        x = self.order.index(key) * self.SLOT
        left, right = self.canvasx(0), self.canvasx(self.winfo_width())
        total = self._total_width()
        if x < left:
            self.xview_moveto(x / total)
        elif x + self.SLOT > right:
            self.xview_moveto(max(0, x + self.SLOT - self.winfo_width()) / total)

    def _total_width(self):
        return max(self.winfo_width(), len(self.order)*self.SLOT+24)

    def begin_follow(self):
        self._cancel_motion()
        self.following = True
        self._follow_fraction = 0.
        self.follow_progress(0)

    def follow_progress(self, fraction):
        if not self.following or not self.order:
            return
        self._follow_fraction = max(self._follow_fraction, min(1., max(0., fraction)))
        # Move toward the active frame as each real conversion milestone arrives.
        position = min(len(self.order)-1, self._follow_fraction*len(self.order))
        center = 8+position*self.SLOT+self.IMAGE[0]/2
        self._motion_target = max(0., min(self._total_width()-self.winfo_width(),
                                         center-self.winfo_width()/2))
        if self._motion_job is None:
            self._motion_clock = time.monotonic()
            self._motion_position = self.canvasx(0)
            self._motion_job = self.after(16, self._advance_view)

    def end_follow(self):
        # Let the last reported position settle; never advance beyond actual work.
        self.following = False

    def _cancel_motion(self):
        if self._motion_job is not None:
            self.after_cancel(self._motion_job)
        self._motion_job = self._motion_target = None

    def _advance_view(self):
        self._motion_job = None
        if self._motion_target is None:
            return
        total = self._total_width()
        target = max(0., min(total-self.winfo_width(), self._motion_target))
        current = self._motion_position
        now = time.monotonic()
        weight = 1-math.exp(-(now-self._motion_clock)/.12)
        self._motion_clock = now
        settled = abs(target-current) <= 1
        offset = target if settled else current+(target-current)*weight
        self._motion_position = offset
        super().xview_moveto(offset/total)
        self.redraw()
        if not settled:
            self._motion_job = self.after(16, self._advance_view)
        else:
            self._motion_target = None

    def xview(self, *args):
        result = super().xview(*args)
        if args:
            self._cancel_motion()
            self.redraw()
        return result

    def xview_moveto(self, fraction):
        self._cancel_motion()
        super().xview_moveto(fraction)
        self.redraw()

    def xview_scroll(self, number, what):
        self._cancel_motion()
        super().xview_scroll(number, what)
        self.redraw()

    def set_thumbnail(self, key, token, image):
        record = self.records.get(key)
        if record is None or record['token'] != token:
            return
        if image is None:
            record['preview'] = None
            record['preview_error'] = True
            self.redraw()
            return
        record['preview'] = image
        self.pending.append((key, token, image))
        if self.animation is None:
            self._next_frame()

    def _next_frame(self):
        self.animation = None
        while self.pending:
            key, token, image = self.pending.popleft()
            if key in self.records and self.records[key]['token'] == token:
                self.animation = (key, token, image, 0)
                self._develop()
                return

    def _develop(self):
        key, token, image, frame = self.animation
        record = self.records.get(key)
        if record is None or record['token'] != token:
            self._next_frame()
            return
        paper = Image.new('RGB', image.size, self.BASE)
        # Develop each frame from paper to the original preview, sequentially.
        record['image'] = Image.blend(paper, image, (frame + 1) / 8)
        record['draw_height'] = None
        self.redraw()
        if frame < 7:
            self.animation = (key, token, image, frame + 1)
            self.animation_job = self.after(35, self._develop)
        else:
            self.animation_job = self.after(45, self._next_frame)

    def destroy(self):
        self._cancel_motion()
        if self.animation_job is not None:
            self.after_cancel(self.animation_job)
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
        super().destroy()

    def _geometry(self):
        gate_height = max(90, min(self.IMAGE[1], self.winfo_height()-112))
        top = max(0, (self.winfo_height()-gate_height-112)/2)
        return top, top+48, gate_height

    def _key_at(self, event):
        x = self.canvasx(event.x)-8
        index = int(x//self.SLOT)
        _, image_y, gate_height = self._geometry()
        if not (image_y <= event.y <= image_y+gate_height+23):
            return None
        if not (0 <= x-index*self.SLOT < self.IMAGE[0]):
            return None
        return self.order[index] if 0 <= index < len(self.order) else None

    def _remove_context(self, event):
        key = self._key_at(event)
        if key is None:
            return 'break'
        self.focus_set()
        if key not in self.selected:
            self.selected = {key}
            self.anchor = key
            self.redraw()
        menu = self.context_menu
        menu.delete(0, 'end')
        menu.add_command(label='查看详情', command=lambda: self._context_detail(key))
        menu.add_command(label='从队列移除', command=self.remove_selected,
                         state='disabled' if self.locked else 'normal')
        try:
            menu.tk_popup(getattr(event, 'x_root', self.winfo_rootx()+event.x),
                          getattr(event, 'y_root', self.winfo_rooty()+event.y))
        finally:
            menu.grab_release()
        return 'break'

    def _context_detail(self, key):
        self.selected = {key}
        self.anchor = key
        self.redraw()
        self.detail()

    def _select(self, event):
        self.focus_set()
        key = self._key_at(event)
        if key is None:
            return
        index = self.order.index(key)
        if event.state & 0x1 and self.anchor in self.order:
            a, b = sorted((self.order.index(self.anchor), index))
            self.selected = set(self.order[a:b+1])
        elif event.state & (0x8 if sys_platform_mac() else 0x4):
            self.selected.symmetric_difference_update({key})
            self.anchor = key
        else:
            self.selected = {key}
            self.anchor = key
        self.selection_changed()
        self.redraw()

    def _all(self, event):
        self.selected = set(self.order)
        self.redraw()
        return 'break'

    def _move(self, delta, event):
        if not self.order:
            return 'break'
        index = self.order.index(self.anchor) if self.anchor in self.order else 0
        key = self.order[max(0, min(len(self.order)-1, index+delta))]
        self.anchor = key
        self.selected = {key}
        self.reveal(key)
        self.redraw()
        return 'break'

    def _detail(self, event=None):
        if event is not None and getattr(event, 'num', None) == 1:
            key = self._key_at(event)
            if key:
                self.selected = {key}
        self.detail()
        return 'break'

    def _wheel(self, event):
        delta = event.delta
        if delta:
            pixels = delta/120*48 if abs(delta)>=120 or not sys_platform_mac() else delta*20
            self._scroll_pixels(-pixels)
        return 'break'

    def _touchpad(self, event):
        dx, dy = map(int, self.tk.splitlist(self.tk.call('tk::PreciseScrollDeltas', event.delta)))
        # Both axes browse this one-dimensional strip; diagonal gestures use
        # their dominant axis rather than doubling the scroll speed.
        self._scroll_pixels(-(dx if abs(dx)>abs(dy) else dy))
        return 'break'

    def _scroll_pixels(self, pixels):
        self._cancel_motion()
        self._wheel_remainder += pixels
        whole = math.trunc(self._wheel_remainder)
        self._wheel_remainder -= whole
        total = self._total_width()
        offset = max(0, min(total-self.winfo_width(), self.canvasx(0)+whole))
        super().xview_moveto(offset/total)
        self.redraw()
        return 'break'

    def redraw(self, event=None):
        if self._redraw_job is None:
            self._redraw_job = self.after_idle(self._paint)

    def _hole(self, x, y):
        # Capsule-shaped perforations cut through the dark film base.
        w, h, r = 14, 22, 7
        self.create_rectangle(x, y+r, x+w, y+h-r, fill='#c7c1aa', outline='', tags='sprocket')
        self.create_oval(x, y, x+w, y+2*r, fill='#c7c1aa', outline='', tags='sprocket')
        self.create_arc(x,y,x+w,y+2*r,start=30,extent=150,style='arc',outline='#777967',width=1,tags='sprocket')
        self.create_oval(x, y+h-2*r, x+w, y+h, fill='#c7c1aa', outline='', tags='sprocket')

    def _empty_label(self, center_x, center_y, width, gate_height):
        """A simple lab label with a stable random number for this session."""
        scale = min(1., max(1, width-32)/280, max(1, gate_height-12)/106)
        left, top = center_x-140*scale, center_y-53*scale
        ink, paper = '#85483c', '#e6d9b9'

        def box(x1, y1, x2, y2, **kwargs):
            return self.create_rectangle(left+x1*scale, top+y1*scale,
                left+x2*scale, top+y2*scale, tags='empty', **kwargs)

        def text(x, y, value, size=10, family='body', **kwargs):
            return self.create_text(left+x*scale, top+y*scale, text=value,
                font=(self.fonts[family], max(7, round(size*scale))),
                fill=ink, tags='empty', **kwargs)

        box(2, 3, 282, 109, fill='#080a08', outline='')
        box(0, 0, 280, 106, fill=paper, outline='#baa889')
        box(7, 7, 273, 99, outline=ink)
        text(23, 38, 'No. '+self.label_number, 13, 'mono', anchor='w')
        text(23, 72, self.label_date, 11, 'mono', anchor='w')
        text(218, 53, 'E-6', 25, 'mono')

    def _paint(self):
        self._redraw_job = None
        self.delete('all')
        width, height = self.winfo_width(), self.winfo_height()
        total = max(width, len(self.order)*self.SLOT+24)
        self.configure(scrollregion=(0, 0, total, height))
        top, image_y, gate_height = self._geometry()
        edge_y = image_y+gate_height+14
        bottom = edge_y+42
        self.create_rectangle(0, top, total, bottom, fill=self.BASE, outline='', tags='base')
        left, right = self.canvasx(0), self.canvasx(width)
        for i in range(max(0,int(left//34)-1), int(right//34)+2):
            self._hole(15+i*34, top+8)
            self._hole(15+i*34, edge_y+12)
        if not self.order:
            self._empty_label((left+right)/2, image_y+gate_height/2, width, gate_height)
        first = max(0, int(left//self.SLOT)-1)
        last = min(len(self.order), int(right//self.SLOT)+2)
        for index in range(first, last):
            key = self.order[index]
            record = self.records[key]
            x = 8+index*self.SLOT
            # One film gate per image, without a separate paper card.
            self.create_rectangle(x, image_y, x+self.IMAGE[0], image_y+gate_height,
                                  fill='#141713', outline='#2a3027', tags=('gate',key))
            if record['image'] is not None:
                if record['draw_height'] != gate_height:
                    preview = record['image'].copy()
                    preview.thumbnail((self.IMAGE[0], round(gate_height)), Image.Resampling.LANCZOS)
                    record['photo'] = ImageTk.PhotoImage(preview, master=self)
                    record['draw_height'] = gate_height
                self.create_image(x+self.IMAGE[0]/2, image_y+gate_height/2,
                                  image=record['photo'], tags=('photo',key))
            else:
                self.create_text(x+self.IMAGE[0]/2, image_y+gate_height/2,
                    text='无预览' if record['preview_error'] else 'NEF',
                    fill='#8e927e', font=(self.fonts['mono'],16), tags=('placeholder',key))
            edge_left, edge_right = x, x+self.IMAGE[0]
            name = record['path'].name
            number = f'{index+1:02}'
            number_width = self.number_font.measure(number)
            while self.edge_font.measure(name)>self.IMAGE[0]-number_width-16 and len(name)>6:
                stem = name.rsplit('…',1)[0] if '…' in name else name[:-len(record['path'].suffix)]
                name = stem[:-1]+'…'+record['path'].suffix
            self.create_text(edge_left, edge_y, text=number, anchor='w', fill=self.EDGE,
                             font=self.number_font, tags=('edge-number',key))
            self.create_text(edge_right, edge_y, text=name, anchor='e', fill=self.EDGE,
                             font=self.edge_font, tags=('edge-name',key))
            state = record['state']
            if key in self.selected:
                # Four small registration corners leave the photograph unobscured.
                for cx, cy, dx, dy in ((x,image_y,1,1),(x+self.IMAGE[0],image_y,-1,1),
                        (x,image_y+gate_height,1,-1),(x+self.IMAGE[0],image_y+gate_height,-1,-1)):
                    points = (cx+dx*9,cy,cx,cy,cx,cy+dy*9)
                    self.create_line(*[v+1 for v in points],fill='#090d09',width=4,tags=('selection',key))
                    self.create_line(*points,fill='#b8b397',width=3,tags=('selection',key))
            if state != 'waiting':
                label = STATE_LABELS.get(state, state)
                symbol = '✓' if state=='complete' else '!' if state in ('failed','complete-warning') else '•'
                color = '#9eaf89' if state=='complete' else '#be9574' if state=='processing' else '#c88a72'
                self.create_text(x+self.IMAGE[0]-3, image_y-12, anchor='e',
                    text=symbol+' '+label, fill=color, font=(self.fonts['body'],9), tags=('result',key))
        if self.drag_over:
            self.create_rectangle(left+2, top+2, right-2, bottom-2, outline=self.EDGE, width=2, dash=(5,3))


def sys_platform_mac():
    import sys
    return sys.platform == 'darwin'


class FilmScroll(tk.Canvas):
    """A borderless position rail outside the film base."""
    def __init__(self, master, film):
        super().__init__(master, height=12, bg=PAPER, highlightthickness=0, bd=0)
        self.film = film
        self.first, self.last = 0., 1.
        self.bind('<Configure>', self._paint)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._paint()

    def _press(self, event):
        width = max(1, self.winfo_width()-12)
        if not self.first*width <= event.x-6 <= self.last*width:
            self.film.xview_moveto((event.x-6)/width-(self.last-self.first)/2)
        self.start_x, self.start_view = event.x, self.film.xview()[0]

    def _drag(self, event):
        self.film.xview_moveto(self.start_view+(event.x-self.start_x)/max(1,self.winfo_width()-12))

    def _paint(self, event=None):
        self.delete('all')
        width = max(1,self.winfo_width()-12)
        self.create_line(6,6,width+6,6,fill='#111914',width=2,capstyle='round')
        if self.last-self.first < .999:
            self.create_line(6+self.first*width,6,6+self.last*width,6,
                             fill='#979f89',width=4,capstyle='round')
