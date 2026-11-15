"""Folded lab label and in-window, keyboard-accessible paper inspection card."""
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageFilter, ImageGrab, ImageStat, ImageTk

from filmstrip import STATE_LABELS
from retro_ui import PhysicalKey

PAPER = '#e7dcc4'
INK = '#754c3b'


class StampKey(PhysicalKey):
    """Paper-printed action; retain the existing mouse and keyboard contract."""
    def _draw(self):
        self.delete('all')
        w,h=int(self.cget('width')),int(self.cget('height'))
        ink='#aa967b' if self.control_state=='disabled' else INK
        self.create_rectangle(2,3,w-3,h-3,outline=ink,width=1,
                              fill='#cebc9b' if self.pressed else '#ded0b3')
        self.create_text(w/2,h/2,text=self.text,font=(self.fonts['body'],10),fill=ink)
        if self.focused:
            self.create_rectangle(5,6,w-6,h-6,outline=ink,dash=(2,2))


class BatchLabel(tk.Canvas):
    def __init__(self, master, fonts, command):
        super().__init__(master, width=310, height=28, bg='#242b27', bd=0,
                         highlightthickness=0, takefocus=True, cursor='hand2')
        self.fonts, self.command = fonts, command
        self.value = ''
        self.bind('<ButtonRelease-1>', lambda e: command())
        self.bind('<Return>', lambda e: command())
        self.bind('<space>', lambda e: command())
        self.bind('<FocusIn>', lambda e: self.paint(True))
        self.bind('<FocusOut>', lambda e: self.paint(False))

    def set(self, number, date):
        self.value = f'No. {number}  ·  {date}  ·  E-6'
        self.paint()

    def paint(self, focused=False):
        self.delete('all')
        self.create_rectangle(2,4,308,27,fill='#111710',outline='')
        self.create_rectangle(0,1,304,24,fill=PAPER,outline='#ad9b7c')
        self.create_polygon(293,1,304,12,293,12,fill='#f4ead5',outline='#bcaa8b')
        self.create_text(12,13,text=self.value,anchor='w',fill=INK,font=(self.fonts['mono'],9))
        if focused:
            self.create_rectangle(4,4,288,21,outline=INK)


class GlassBackdrop(tk.Canvas):
    """A softened snapshot of the application under the paper page."""
    def __init__(self, master):
        super().__init__(master, bg='#d6d2c5', bd=0, highlightthickness=0)
        self._surface = None
        self._photo = None
        self.bind('<Configure>', self._paint)

    def capture(self):
        self._surface = None
        self.master.update_idletasks()
        width, height = max(1, self.master.winfo_width()), max(1, self.master.winfo_height())
        if self.master.winfo_ismapped():
            x, y = self.master.winfo_rootx(), self.master.winfo_rooty()
            try:
                captured = ImageGrab.grab(bbox=(x, y, x + width, y + height)).convert('RGB')
                if captured.size != (width, height):
                    captured = captured.resize((width, height), Image.Resampling.LANCZOS)
                stats = ImageStat.Stat(captured)
                if not (max(stats.mean) < 6 or min(stats.mean) > 249 or max(stats.stddev) < 1.2):
                    blurred = captured.filter(ImageFilter.GaussianBlur(13))
                    veil = Image.new('RGB', (width, height), '#d8d6ca')
                    self._surface = Image.blend(blurred, veil, .43)
            except Exception:
                self._surface = None
        if self._surface is None:
            # Keep the glass treatment calm if this platform denies screen capture.
            self._surface = Image.new('RGB', (width, height), '#d4d2c7')
        self._paint()

    def _paint(self, event=None):
        if self._surface is None:
            return
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        surface = self._surface
        if surface.size != (width, height):
            surface = surface.resize((width, height), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(surface, master=self)
        self.delete('all')
        self.create_image(0, 0, image=self._photo, anchor='nw')


class PhotoGrid(tk.Frame):
    """Three-column contact sheet with an action pair on every photograph."""
    def __init__(self, master, fonts, image_lookup, detail, locate, close):
        super().__init__(master, bg=PAPER)
        self.fonts, self.image_lookup = fonts, image_lookup
        self.detail, self.locate, self.close = detail, locate, close
        self.canvas = tk.Canvas(self, bg=PAPER, bd=0, highlightthickness=0)
        self.inner = tk.Frame(self.canvas, bg=PAPER)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.scrollbar = PaperScroll(self, self.canvas)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y', padx=(8, 0))
        self.canvas.bind('<Configure>', self._resize_inner)
        self.inner.bind('<Configure>', self._update_scrollregion)
        self._wheel_remainder = 0.
        self.canvas.bind('<MouseWheel>', self._wheel)
        try:
            self.canvas.bind('<TouchpadScroll>', self._touchpad)
        except tk.TclError:
            pass

    def _resize_inner(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def _update_scrollregion(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _wheel(self, event):
        delta = event.delta
        pixels = delta / 120 * 48 if abs(delta) >= 120 else delta * 20
        return self._scroll_pixels(-pixels)

    def _touchpad(self, event):
        dx, dy = map(int, self.tk.splitlist(
            self.tk.call('tk::PreciseScrollDeltas', event.delta)))
        return self._scroll_pixels(-(dx if abs(dx) > abs(dy) else dy))

    def _scroll_pixels(self, pixels):
        self._wheel_remainder += pixels
        units = int(self._wheel_remainder / 20)
        self._wheel_remainder -= units * 20
        if units:
            self.canvas.yview_scroll(units, 'units')
        return 'break'

    def position(self):
        return self.canvas.yview()[0]

    def restore(self, position):
        self.canvas.yview_moveto(position)

    def render(self, records, selected=None):
        position = self.position()
        for child in self.inner.winfo_children():
            child.destroy()
        columns = 3
        for column in range(columns):
            self.inner.columnconfigure(column, weight=1, uniform='photo-columns')
        for index, record in enumerate(records):
            key = record['key']
            selected_photo = key == selected
            tile = tk.Frame(self.inner, bg='#e3d7bd',
                            highlightbackground='#9b805d' if selected_photo else '#c3b08d',
                            highlightthickness=2 if selected_photo else 1, padx=8, pady=8)
            tile.grid(row=index // columns, column=index % columns,
                      sticky='nsew', padx=6, pady=6)
            tile.columnconfigure(0, weight=1)

            image_record = self.image_lookup(key) or {}
            image = image_record.get('preview') or image_record.get('image')
            if image is None:
                preview = tk.Label(tile,
                    text='无预览' if image_record.get('preview_error') else '预览读取中',
                    bg='#20241f', fg='#c6b99f', font=(self.fonts['mono'], 11), height=8)
                preview.pack(fill='x')
            else:
                thumb = image.copy()
                thumb.thumbnail((260, 166), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(thumb, master=tile)
                preview = tk.Label(tile, image=photo, bg='#20241f', cursor='hand2')
                preview.image = photo
                preview.pack(fill='x')
                preview.bind('<Button-1>', lambda event, k=key: self.detail(k))

            filename = tk.Label(tile, text=f'{index + 1:02d}  {Path(key).name}',
                                bg='#e3d7bd', fg=INK,
                                font=(self.fonts['body'], 10), anchor='w',
                                justify='left', wraplength=258)
            filename.pack(fill='x', pady=(7, 2))
            state = record['state']
            tk.Label(tile, text=STATE_LABELS.get(state, state), bg='#e3d7bd',
                     fg='#984e3c' if state == 'failed' else '#484f60',
                     font=(self.fonts['mono'], 9), anchor='w').pack(fill='x')
            actions = tk.Frame(tile, bg='#e3d7bd')
            actions.pack(anchor='w', pady=(7, 0))
            view_button = StampKey(actions, '查看详情', lambda k=key: self.detail(k),
                                   self.fonts, bg='#e3d7bd', width=78, height=27)
            view_button.pack(side='left', padx=(0, 7))
            view_button.bind('<Escape>', lambda event: self.close())
            locate_button = StampKey(actions, '定位照片', lambda k=key: self.locate(k),
                                     self.fonts, bg='#e3d7bd', width=78, height=27)
            locate_button.pack(side='left')
            locate_button.bind('<Escape>', lambda event: self.close())
            self._bind_scroll(tile)
        self.inner.update_idletasks()
        self._update_scrollregion()
        self.canvas.yview_moveto(position)

    def _bind_scroll(self, widget):
        widget.bind('<MouseWheel>', self._wheel, add='+')
        try:
            widget.bind('<TouchpadScroll>', self._touchpad, add='+')
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._bind_scroll(child)


class InspectionCard(tk.Frame):
    """Full-window registration page for one batch or one photograph."""
    def __init__(self, master, fonts, locate, detail, image_lookup=None):
        super().__init__(master, bg=PAPER, highlightbackground='#b6a180', highlightthickness=2,
                         padx=20, pady=16)
        self.fonts, self.locate, self.detail = fonts, locate, detail
        self.image_lookup = image_lookup or (lambda key: {})
        self.glass = GlassBackdrop(master)
        available = set(tkfont.families(self))
        self.hand = next((name for name in ('LXGW WenKai Mono', 'Kaiti SC', 'KaiTi') if name in available), fonts['body'])
        self.visible = False
        self.card_mode = None
        self.return_focus = None
        self.title = tk.Label(self, bg=PAPER, fg=INK, font=(fonts['body'],18), anchor='w')
        self.title.pack(fill='x', padx=(0,70))
        self.close_button = StampKey(self,'收起',self.hide,fonts,width=64,height=28,bg=PAPER)
        self.close_button.place(relx=1,x=0,y=0,anchor='ne')
        self.subtitle = tk.Frame(self, bg=PAPER)
        self.subtitle.pack(fill='x', pady=(7,9))
        tk.Frame(self,bg='#c4b394',height=1).pack(fill='x')
        body = self.body = tk.Frame(self,bg=PAPER)
        body.pack(fill='both',expand=True,pady=(8,0))
        self.text = tk.Text(body, bg=PAPER, fg='#4e4b3e', font=(fonts['body'],11),
                            wrap='word', bd=0, highlightthickness=0, padx=2, pady=4,
                            cursor='arrow', spacing1=2, spacing3=4, height=8)
        self.scrollbar = PaperScroll(body,self.text)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.tag_configure('heading',foreground=INK,font=(fonts['body'],12,'bold'))
        self.text.tag_configure('failure',foreground='#984e3c')
        self.text.tag_configure('muted',foreground='#77705e')
        self.text.tag_configure('hand',foreground='#484f60',font=(self.hand,12))
        self.text.tag_configure('hand-failure',foreground='#8b5149',font=(self.hand,12))
        self.text.tag_configure('link',foreground=INK,underline=False,
                                font=(fonts['body'],10),background='#d9c9aa',
                                relief='solid',borderwidth=1)
        self.text.tag_bind('link','<Enter>',lambda e:self.text.configure(cursor='hand2'))
        self.text.tag_bind('link','<Leave>',lambda e:self.text.configure(cursor='arrow'))
        self.text.bind('<MouseWheel>',lambda e: 'break' if self.card_mode=='batch' else None)
        try:
            self.text.bind('<TouchpadScroll>',lambda e: 'break' if self.card_mode=='batch' else None)
        except tk.TclError:
            pass
        self.detail_stage = tk.Frame(body, bg='#20241f', width=410)
        self.detail_stage.pack_propagate(False)
        self.detail_preview = tk.Label(self.detail_stage, bg='#20241f', fg='#c6b99f',
                                       text='预览读取中', font=(fonts['mono'],11))
        self.detail_preview.pack(fill='both', expand=True)
        self.detail_photo = None
        self.photo_grid = PhotoGrid(body, fonts, self.image_lookup, detail, locate, self.hide)
        self.actions = tk.Frame(self,bg=PAPER)
        self.bind('<Escape>',lambda e: self.hide())
        for child in (self.text,self.close_button):
            child.bind('<Escape>',lambda e: self.hide())
        self.bind('<Configure>',self._wrap_subtitle)

    def show(self, title, subtitle):
        if not self.visible:
            self.return_focus = self.focus_get()
            self.glass.capture()
            self.glass.place(x=0, y=0, relwidth=1, relheight=1)
            # Canvas.lower() addresses canvas items; use Tk's window stacking
            # command to place the backdrop below this sibling frame.
            self.glass.tk.call('lower', self.glass._w, self._w)
        self.visible = True
        self.title.configure(text=title)
        self._subtitle([(subtitle,False)])
        self.place(x=22,y=22,relwidth=1,relheight=1,width=-44,height=-44)
        self.lift()
        self.text.pack_forget()
        self.scrollbar.pack_forget()
        self.photo_grid.pack_forget()
        self.detail_stage.pack_forget()
        self.text.configure(state='normal')
        self.text.delete('1.0','end')
        for tag in self.text.tag_names():
            if tag.startswith('action-'):
                self.text.tag_delete(tag)
        for child in self.actions.winfo_children():
            child.destroy()
        self.actions.pack(side='bottom',fill='x',pady=(6,0),before=self.body)
        self.close_button.focus_set()

    def _subtitle(self, parts):
        for child in self.subtitle.winfo_children():
            child.destroy()
        for text, handwritten in parts:
            tk.Label(self.subtitle,text=text,bg=PAPER,
                     fg='#484f60' if handwritten else INK,
                     font=(self.hand,11) if handwritten else (self.fonts['mono'],10),
                     padx=0,pady=0,anchor='w').pack(side='left')
        self._wrap_subtitle()

    def _wrap_subtitle(self, event=None):
        children=self.subtitle.winfo_children()
        if len(children)==1:
            children[0].configure(wraplength=max(200,self.winfo_width()-40))
        elif children:
            children[-1].configure(wraplength=max(200,self.winfo_width()-180))

    def scroll_position(self):
        if self.card_mode == 'batch':
            return self.photo_grid.position()
        return self.text.yview()[0]

    def restore_scroll(self, position):
        if self.card_mode == 'batch':
            self.photo_grid.restore(position)
        else:
            self.text.yview_moveto(position)

    def hide(self):
        was_visible = self.visible
        self.visible = False
        self.place_forget()
        self.glass.place_forget()
        if was_visible:
            self._expose_underlay(self.master)
        if self.return_focus is not None and self.return_focus.winfo_exists():
            self.return_focus.focus_set()
        return 'break'

    @staticmethod
    def _expose_underlay(widget):
        # On macOS, unmapping a placed Frame inside a Canvas window can leave
        # its pixels in the backing store. Repaint the parent background and
        # its mapped children, including the film and scroll canvases.
        if not widget.winfo_ismapped():
            return
        widget.event_generate('<Expose>', width=widget.winfo_width(),
                              height=widget.winfo_height(), when='tail')
        for child in widget.winfo_children():
            InspectionCard._expose_underlay(child)

    def action(self, label, command):
        width=max(64,tkfont.Font(self,font=(self.fonts['body'],10)).measure(label)+28)
        button = StampKey(self.actions,label,command,self.fonts,bg=PAPER,width=width,height=28)
        button.pack(side='left',padx=(0,8))
        button.bind('<Escape>',lambda e:self.hide())

    def show_batch(self, number, date, records, output, outcome, selected=None):
        self.card_mode = 'batch'
        success = sum(r['state'] in ('complete','complete-warning') for r in records)
        failed = sum(r['state']=='failed' for r in records)
        waiting = len(records)-success-failed
        self.show('冲印记录', f'No. {number}   ·   {date}   ·   E-6')
        self._subtitle([('No. ',False),(str(number),True),('   ·   ',False),
                        (date,True),('   ·   E-6',False)])
        self.text.insert('end',outcome,'hand')
        for label,value,suffix in [('  ·  共 ',len(records),' 张'),('  ·  成功 ',success,''),
                                   ('  ·  失败 ',failed,''),('  ·  待完成 ',waiting,'')]:
            self.text.insert('end',label,'heading')
            self.text.insert('end',str(value),'hand')
            self.text.insert('end',suffix,'heading')
        self.text.insert('end','\n输出目录  ','muted')
        self.text.insert('end',str(output),'hand')
        self.text.insert('end','\n\n')
        for index,record in enumerate(records):
            key = record['key']
            self.text.insert('end', f'{index+1:02}  {Path(key).name}  ·  {STATE_LABELS.get(record["state"],record["state"])}\n',
                             'hand-failure' if record['state']=='failed' else 'hand')
            for label,command in [('查看详情',lambda k=key:self.detail(k)),
                                  ('定位照片',lambda k=key:self.locate(k))]:
                tag=f'action-{index}-{label}'
                self.text.insert('end','  '+label+'  ',('link',tag))
                self.text.insert('end','    ')
                self.text.tag_bind(tag,'<Button-1>',lambda e,cmd=command:cmd())
            self.text.insert('end','\n')
        self.text.configure(state='disabled', height=3)
        self.text.pack(side='top',fill='x')
        self.photo_grid.pack(side='top',fill='both',expand=True,pady=(6,0))
        self.scrollbar.pack_forget()
        self.detail_stage.pack_forget()
        self.photo_grid.render(records, selected)
        # All row actions have keyboard equivalents, independent of Text tags.
        keys = [r['key'] for r in records]
        if keys:
            self.row_index = keys.index(selected) if selected in keys else 0
            self.row_choice = tk.StringVar(value=Path(keys[self.row_index]).name)
            def move(delta):
                self.row_index = max(0,min(len(keys)-1,self.row_index+delta))
                self.row_choice.set(Path(keys[self.row_index]).name)
            self.action('上一张',lambda:move(-1))
            self.action('下一张',lambda:move(1))
            self.action('查看详情',lambda:self.detail(keys[self.row_index]))
            self.action('定位照片',lambda:self.locate(keys[self.row_index]))
            tk.Label(self.actions,textvariable=self.row_choice,bg=PAPER,fg=INK,
                     font=(self.hand,10),anchor='w').pack(side='left',fill='x',expand=True)

    def show_detail(self, record, number, back=None):
        self.card_mode = 'detail'
        self.show('检片详情',f"No. {number}  ·  {Path(record['key']).name}")
        self._subtitle([('No. ',False),(str(number),True),('  ·  ',False),
                        (Path(record['key']).name,True)])
        self.detail_stage.pack(side='left',fill='both',padx=(0,20))
        self.text.configure(height=8)
        self.text.pack(side='left',fill='both',expand=True)
        self.scrollbar.pack(side='right',fill='y')
        image_record = self.image_lookup(record['key']) or {}
        image = image_record.get('preview') or image_record.get('image')
        self.detail_photo = None
        if image is None:
            self.detail_preview.configure(image='', text='无预览' if image_record.get('preview_error') else '预览读取中')
        else:
            preview = image.copy()
            scale = min(1.6, 380 / max(1, preview.width), 380 / max(1, preview.height))
            if scale > 1:
                preview = preview.resize((round(preview.width * scale), round(preview.height * scale)),
                                         Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(preview, master=self.detail_preview)
            self.detail_photo = photo
            self.detail_preview.configure(image=photo, text='')
        handwriting = 'hand-failure' if record['state']=='failed' else 'hand'
        self.text.insert('end','状态  ','heading')
        self.text.insert('end',STATE_LABELS.get(record['state'],record['state'])+'\n',handwriting)
        self.text.insert('end','源文件\n','muted')
        self.text.insert('end',record['key']+'\n\n','hand')
        self.text.insert('end',record.get('detail') or '尚无转换结果。',handwriting)
        self.text.configure(state='disabled')
        if back is not None:
            self.action('返回记录',back)
            self.action('定位照片',lambda:self.locate(record['key']))
        else:
            self.actions.pack_forget()


class PaperScroll(tk.Canvas):
    """A subtle vertical position rail, blank when the entire card fits."""
    def __init__(self, master, text):
        super().__init__(master,width=10,bg=PAPER,bd=0,highlightthickness=0)
        self.text = text
        self.first,self.last = 0.,1.
        self.bind('<Configure>',lambda e:self.paint())
        self.bind('<Button-1>',self.press)
        self.bind('<B1-Motion>',self.drag)

    def set(self, first, last):
        self.first,self.last = float(first),float(last)
        self.paint()

    def paint(self):
        self.delete('all')
        if self.last-self.first >= .999:
            return
        height = max(1,self.winfo_height()-8)
        self.create_line(5,4,5,height+4,fill='#c7b897',width=1)
        self.create_line(5,4+self.first*height,5,4+self.last*height,
                         fill='#a99572',width=3,capstyle='round')

    def press(self,event):
        height = max(1,self.winfo_height()-8)
        fraction = (event.y-4)/height
        if not self.first <= fraction <= self.last:
            self.text.yview_moveto(fraction-(self.last-self.first)/2)
        self.start_y,self.start_view = event.y,self.text.yview()[0]

    def drag(self,event):
        self.text.yview_moveto(self.start_view+(event.y-self.start_y)/max(1,self.winfo_height()-8))
