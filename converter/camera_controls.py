"""Native vector controls inspired by mechanical camera dials and timers."""
import math
import tkinter as tk

from retro_ui import PAPER, CARD, INK, MUTED, LINE, ACCENT, PRINT, lcd, panel_text, material, draw_dial

IDLE_READOUT = 'At the Heart of the Image 📷'


class DialSelector(tk.Canvas):
    DIAL_CENTER = (80, 92)
    DIAL_HIT_RADIUS = 56
    LABEL_RADIUS = 68
    DISPLAY_LEFT = 210
    DISPLAY_TOP = 46
    DISPLAY_HEIGHT = 45

    def __init__(self, master, fonts, title, values, marks):
        super().__init__(master, width=430, height=172, bg=CARD, bd=0,
                         highlightthickness=0, takefocus=True, cursor='')
        self.fonts, self.title, self.values, self.marks = fonts, title, values, marks
        self.index = 0
        self.drag_position = None
        self.control_state = 'readonly'
        self.focused = False
        self.dragged = False
        self.armed = False
        self.start_y = 0
        self.bind('<Configure>', self._draw)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<MouseWheel>', self._wheel)
        self.bind('<Motion>',self._pointer)
        self.bind('<Leave>',lambda event:super(DialSelector,self).configure(cursor=''))
        for key, step in [('Left', -1), ('Down', -1), ('Right', 1), ('Up', 1), ('space', 1)]:
            self.bind('<'+key+'>', lambda e, d=step: self.step(d))
        self.bind('<Home>', lambda e: self.choose(0))
        self.bind('<End>', lambda e: self.choose(len(self.values)-1))
        self.bind('<FocusIn>', lambda e: self._focus(True))
        self.bind('<FocusOut>', lambda e: self._focus(False))
        self._draw()

    def current(self, index=None):
        if index is None:
            return self.index
        if not 0 <= index < len(self.values):
            raise IndexError(index)
        self.index = index
        self.drag_position = None
        self._draw()

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf or {}, **kwargs)
        if 'state' in options:
            self.control_state = options.pop('state')
            self.armed = False
            self.drag_position = None
            super().configure(cursor='',
                              takefocus=self.control_state!='disabled')
            self._draw()
        if options:
            return super().configure(**options)

    def choose(self, index):
        if self.control_state != 'disabled':
            if index != self.index:
                self.current(index)
                self.event_generate('<<DialChanged>>')
        return 'break'

    def step(self, amount):
        return self.choose(max(0, min(len(self.values)-1, self.index+amount)))

    def _focus(self, on):
        self.focused = on
        self._draw()

    def _on_knob(self,event):
        cx,cy=self.DIAL_CENTER
        return (event.x-cx)**2+(event.y-cy)**2 <= self.DIAL_HIT_RADIUS**2

    def _pointer(self,event):
        super().configure(cursor='hand2' if self.control_state!='disabled' and self._on_knob(event) else '')

    def _press(self, event):
        self.armed = self.control_state!='disabled' and self._on_knob(event)
        if not self.armed:
            return
        self.focus_set()
        self.start_y, self.start_x, self.start_index = event.y, event.x, self.index
        self.dragged = False

    def _drag(self, event):
        if self.control_state == 'disabled' or not self.armed:
            return
        offset = event.x-self.start_x + self.start_y-event.y
        if abs(offset)>8:
            self.dragged = True
            self.drag_position = max(0., min(len(self.values)-1., self.start_index+offset/22))
            self._draw()

    def _release(self, event):
        armed,self.armed = self.armed,False
        if self.control_state == 'disabled' or not armed:
            return
        if self.dragged:
            target = int(self.drag_position + .5)
            self.drag_position = None
            self.choose(target)
        elif self._on_knob(event):
            # A click turns toward the side pressed; no wrap across the stop.
            self.step(-1 if event.x < self.DIAL_CENTER[0] else 1)
        self._draw()

    def _wheel(self, event):
        if self._on_knob(event) and event.delta:
            self.step(1 if event.delta>0 else -1)
            return 'break'

    def display_bounds(self):
        width = max(300, self.winfo_width()) if self.winfo_width()>1 else 430
        display_width = min(205, max(186, round((width-190)*.55)))
        return (self.DISPLAY_LEFT,self.DISPLAY_TOP,
                self.DISPLAY_LEFT+display_width,self.DISPLAY_TOP+self.DISPLAY_HEIGHT)

    def _draw(self, event=None):
        self.delete('all')
        disabled = self.control_state=='disabled'
        bounds=self.display_bounds()
        panel_text(self,bounds[0],bounds[1]-20,self.title,self.fonts,
                   anchor='w',fill='#bfc2ab')
        lcd(self,bounds,self.values[self.index],self.fonts,11,
            disabled=disabled,text_inset=5)
        position = self.index if self.drag_position is None else self.drag_position
        angle = math.radians(-150+position*120/max(1,len(self.values)-1))
        draw_dial(self,angle,disabled,center=self.DIAL_CENTER,output_size=128)
        for i, mark in enumerate(self.marks):
            r=math.radians(-150+i*120/max(1,len(self.values)-1))
            panel_text(self,self.DIAL_CENTER[0]+self.LABEL_RADIUS*math.cos(r),
                       self.DIAL_CENTER[1]+self.LABEL_RADIUS*math.sin(r),mark,self.fonts,10,anchor='center',
                       fill='#cfb77d' if i==self.index and not disabled else '#a6ac97')
        if self.focused and not disabled:
            cx,cy=self.DIAL_CENTER
            radius=self.DIAL_HIT_RADIUS
            self.create_oval(cx-radius,cy-radius,cx+radius,cy+radius,
                             outline='#b8ab7b',width=1,tags='knob-focus')


class TimerButton(tk.Canvas):
    """A spring lever returns to rest as reported conversion work completes."""
    def __init__(self, master, command, fonts):
        super().__init__(master,width=310,height=89,bg=CARD,bd=0,
                         highlightthickness=0,takefocus=True,cursor='hand2')
        self.command,self.fonts = command,fonts
        self.readout_changed = lambda: None
        self.control_state='normal'
        self.active=False
        self.progress=self.target=0.0
        self.total=self.completed=0
        self.success=self.failed=0
        self.result=None
        self.pressed=self.hover=self.focused=False
        self.job=None
        self.bind('<Enter>',lambda e:self._flag('hover',True))
        self.bind('<Leave>',self._leave)
        self.bind('<ButtonPress-1>',self._press)
        self.bind('<ButtonRelease-1>',self._release)
        self.bind('<Return>',self._keyboard)
        self.bind('<space>',self._keyboard)
        self.bind('<FocusIn>',lambda e:self._flag('focused',True))
        self.bind('<FocusOut>',lambda e:self._flag('focused',False))
        self._draw()

    def configure(self,cnf=None,**kwargs):
        options=dict(cnf or {},**kwargs)
        if 'state' in options:
            self.control_state=options.pop('state')
            self.pressed=False
            super().configure(cursor='' if self.control_state=='disabled' else 'hand2')
            self._draw()
        if options:
            return super().configure(**options)

    def reset(self):
        if self.job is not None:
            self.after_cancel(self.job)
            self.job=None
        self.active=False
        self.total=self.completed=0
        self.success=self.failed=0
        self.progress=self.target=0.0
        self.result=None
        self._draw()

    def begin(self,total):
        self.reset()
        self.active=True
        self.total=total
        self._draw()

    def update_progress(self,fraction,completed=None):
        self.target=max(self.target,min(1,max(0,fraction)))
        if completed is not None:
            self.completed=completed
        if self.job is None:
            self._tick()

    def finish(self,stopped=False,success=0,failed=0):
        self.active=False
        self.success,self.failed=success,failed
        self.result=('已停止' if stopped else
                     '转换失败' if failed and not success else
                     '部分失败' if failed else '转换完成')
        if not stopped:
            self.update_progress(1,self.total)
        self._draw()

    def _tick(self):
        self.job=None
        if abs(self.target-self.progress)<.002:
            self.progress=self.target
        else:
            self.progress+=(self.target-self.progress)*.24
            self.job=self.after(30,self._tick)
        self._draw()

    def readout(self):
        if self.active:
            return f'转换中 {int(self.progress*100):02d}% · {self.completed} / {self.total}'
        if self.result:
            return f'{self.result} · 成功{self.success} 失败{self.failed}'
        return IDLE_READOUT

    def _flag(self,key,value):
        setattr(self,key,value)
        self._draw()

    def _leave(self,event):
        self.pressed=self.hover=False
        self._draw()

    def _press(self,event):
        if self.control_state!='disabled':
            self.focus_set()
            self._flag('pressed',True)

    def _release(self,event):
        activate=self.pressed and 0<=event.x<self.winfo_width() and 0<=event.y<self.winfo_height()
        self._flag('pressed',False)
        if activate and self.control_state!='disabled':
            self.command()

    def _keyboard(self,event):
        if self.control_state!='disabled':
            self.command()
        return 'break'

    def destroy(self):
        if self.job is not None:
            self.after_cancel(self.job)
        super().destroy()

    def _draw(self):
        self.delete('all')
        depth = 3 if self.pressed or self.active else 0
        # Recessed mounting socket, thick casting and a raised, beveled key face.
        material(self,(0,3,309,88),'panel')
        material(self,(4,4+depth,305,80+depth),'key',pressed=bool(depth))
        if self.focused:
            self.create_rectangle(2,2,307,86,outline='#c8b580')
        shell_items=set(self.find_all())
        # Brushed metal hub, engraved travel marks, and a red-tipped FM2-style lever.
        cx,cy=48,44
        for a in range(110,291,15):
            r=math.radians(a)
            self.create_line(cx+29*math.cos(r),cy+29*math.sin(r),
                             cx+33*math.cos(r),cy+33*math.sin(r),fill='#998d76')
        self.create_oval(cx-23,cy-20,cx+24,cy+26,fill='#303b2e',outline='')
        self.create_oval(cx-23,cy-23,cx+23,cy+23,fill='#959b88',outline='#c5cab8')
        self.create_arc(cx-23,cy-23,cx+23,cy+23,start=35,extent=155,style='arc',outline='#ecebd8',width=2)
        self.create_arc(cx-23,cy-23,cx+23,cy+23,start=215,extent=145,style='arc',outline='#555f4f',width=2)
        self.create_oval(cx-20,cy-20,cx+20,cy+20,fill='#d4d2bd',outline='#686f5e')
        self.create_oval(cx-17,cy-17,cx+17,cy+17,fill='#e1dfcd',outline='#f8f3dc')
        angle=math.radians(110+180*self.progress if self.active or self.result else 290)
        ux,uy=math.cos(angle),math.sin(angle)
        vx,vy=-uy,ux
        points=[cx-5*vx,cy-5*vy,cx+25*ux-6*vx,cy+25*uy-6*vy,
                cx+32*ux-3*vx,cy+32*uy-3*vy,cx+32*ux+3*vx,cy+32*uy+3*vy,
                cx+25*ux+6*vx,cy+25*uy+6*vy,cx+5*vx,cy+5*vy]
        self.create_polygon([v+1.5 for v in points],fill='#4a5345',outline='')
        self.create_polygon(points,fill='#c7c7b4',outline='#7b8270',width=1.5)
        self.create_line(cx-3*vx,cy-3*vy,cx+25*ux-3*vx,cy+25*uy-3*vy,fill='#efebd7')
        self.create_line(cx+20*ux,cy+20*uy,cx+29*ux,cy+29*uy,fill=ACCENT,width=6,capstyle='round')
        self.create_oval(cx-8,cy-8,cx+8,cy+8,fill='#d6d0c0',outline='#8f846f')
        self.create_line(cx-3,cy+3,cx+3,cy-3,fill='#6f675a',width=1.5)
        panel_text(self,190,43,'转换',self.fonts,16,anchor='center',fill='#3a4437',dark=True)
        if depth:
            for item in self.find_all():
                if item not in shell_items:
                    self.move(item,0,depth)
        self.readout_changed()
