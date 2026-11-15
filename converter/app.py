"""Photographic desktop interface; RAW conversion remains in converter.py."""
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES

from converter import VERSION, HOME, collect, convert, cli
from platform_support import open_path
from retro_ui import PAPER, CARD, INK, MUTED, LINE, FILM, setup_theme, Paper, icon, TypeLabel, register_fonts, WOOD, PRINT, LCD, ConsolePlate, PhysicalKey, PanelLabel
from filmstrip import FilmStrip, FilmScroll, load_thumbnail
from camera_controls import DialSelector, TimerButton, IDLE_READOUT
from window_chrome import integrated_titlebar
from batch_card import BatchLabel, InspectionCard
from datetime import datetime
from secrets import randbelow

# Core milestones determine progress; no wall-clock countdown is implied.
STAGE_FRACTIONS = {'读取 NEF 与拍摄信息': .02, '映射颜色与生成目标 RAW': .18,
                   '编码 RW2': .43, '验证 RAW 并更新照片预览': .72, '完成': .98}


def create_root():
    register_fonts()  # Register before Tk caches font families.
    return TkinterDnD.Tk()


class Application:
    def __init__(self, root):
        self.root = root
        self.files = []
        self.running = False
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.closed = threading.Event()
        self.thumbnail_pause = threading.Event()
        self.thumbnails = queue.Queue()
        self.next_token = 0
        self.details = {}
        self.undo_snapshot = None
        self.batch_records = None
        self.batch_output = None
        self.new_batch_pending = False
        self.icons = {}
        root.title('Zf2Lumix')
        root.geometry('1080x850')
        root.minsize(980, 800)
        self.fonts = setup_theme(root)
        paper = Paper(root)
        paper.pack(fill='both', expand=True)
        self.count = tk.StringVar(value='00 张照片')
        self.count_display = LCD(paper, self.count, self.fonts, width=160, height=44, bg=WOOD, size=14)
        self.count_display.place(relx=1, x=-36, y=28, anchor='ne')
        rail = self.rail = ConsolePlate(paper, color='#242b27', inset=16, top_inset=44, height=264)
        rail.pack(fill='both', expand=True, padx=34, pady=(98,0))
        self.clear_button = PhysicalKey(rail, '清空', self.clear, self.fonts, width=64, height=28, bg='#242b27')
        self.clear_button.place(relx=1, x=-28, y=8, anchor='ne')
        self.import_button = PhysicalKey(rail, '导入', self.import_photos, self.fonts, width=64, height=28, bg='#242b27')
        self.import_button.place(relx=1, x=-100, y=8, anchor='ne')
        album = rail.body
        self.film = FilmStrip(album, self.fonts, self.add, self.show_detail, remove=self.remove)
        self.film.configure(bg='#242b27')
        scroll = self.film_scroll = FilmScroll(album, self.film)
        scroll.configure(bg='#242b27')
        scroll.pack(side='bottom', fill='x', pady=(8, 0))
        self.film.pack(fill='both', expand=True)
        self.film.configure(xscrollcommand=scroll.set)
        self.batch_label = BatchLabel(rail, self.fonts, self.toggle_batch)
        self.batch_label.set(self.film.label_number,self.film.label_date)
        self.undo_button = PhysicalKey(rail, '撤销移除', self.undo_remove, self.fonts,
                                       width=88, height=28, bg='#242b27')
        self.card = InspectionCard(paper,self.fonts,self.locate_photo,
                                   lambda key:self.show_detail(key,from_batch=True),
                                   image_lookup=lambda key:self.film.records.get(key))
        self.film.bind('<BackSpace>', lambda e: self.remove())
        self.film.bind('<Delete>', lambda e: self.remove())
        panel = ConsolePlate(paper, height=294)
        panel.pack(fill='x', padx=34, pady=(22,28))
        opts = panel.body
        output_row = tk.Frame(opts, bg=CARD)
        output_row.pack(fill='x', pady=(0,8))
        PanelLabel(output_row, '输出目录', self.fonts).pack(side='left', padx=(0,16))
        self.output = tk.StringVar(value=str(Path.home()/'Pictures/Zf2Lumix'))
        self.reveal_button = PhysicalKey(output_row, '打开', self.reveal_output, self.fonts, width=100)
        self.reveal_button.pack(side='right', padx=(8,0))
        self.output_button = PhysicalKey(output_row, '选择', self.choose_output, self.fonts, width=100)
        self.output_button.pack(side='right', padx=(16,0))
        self.output_display = LCD(output_row, self.output, self.fonts)
        self.output_display.pack(side='left', fill='x', expand=True)
        tk.Frame(opts, bg='#545e53', height=1).pack(fill='x', pady=(2,8))
        controls = tk.Frame(opts, bg=CARD)
        controls.pack(fill='x')
        controls.columnconfigure(0, weight=1)
        self.profile = DialSelector(controls, self.fonts, '颜色校准',
            ['自动（按拍摄白平衡）', '日光校准', '暖光校准'], ['自动', '日光', '暖光'])
        self.profile.grid(row=0, column=0, rowspan=2, sticky='ew', padx=(0, 20))
        tk.Frame(controls, bg=CARD, width=1).grid(row=0, column=1, sticky='ns')
        self.start_button = TimerButton(controls, self.start, self.fonts)
        self.start_button.grid(row=0, column=2, padx=(24,0), pady=(22,0))
        self.status = tk.StringVar(value='')
        self.readout = tk.StringVar(value=IDLE_READOUT)
        self.status_display = LCD(controls, self.readout, self.fonts, width=310,
                                  height=34, size=12, anchor='w')
        self.status_display.grid(row=1, column=2, padx=(24,0), pady=(8,0))
        self.start_button.readout_changed = self._refresh_readout
        self.status.trace_add('write', self._refresh_readout)
        divider = tk.Frame(controls, bg='#545e53', width=1)
        def position_divider():
            display_edge = self.profile.winfo_x()+self.profile.display_bounds()[2]
            x = round((display_edge+self.start_button.winfo_x())/2)
            divider.place(x=x,y=12,width=1,height=max(1,controls.winfo_height()-24))
        controls.bind('<Configure>',lambda event: controls.after_idle(position_divider))
        self._menu()
        self.integrated_titlebar = integrated_titlebar(root)
        if self.integrated_titlebar:
            paper._window_control_mount()
        threading.Thread(target=self.thumbnail_worker, daemon=True).start()
        root.after(60, self.poll)

    def _refresh_readout(self, *args):
        self.readout.set(self.status.get() or self.start_button.readout())

    def _menu(self):
        root = self.root
        menu = tk.Menu(root)
        files_menu = tk.Menu(menu, tearoff=False)
        files_menu.add_command(label='导入文件…', command=self.import_photos, accelerator='⌘O' if sys.platform=='darwin' else 'Ctrl+O')
        files_menu.add_command(label='选择输出目录…', command=self.choose_output)
        files_menu.add_command(label='冲印记录', command=self.toggle_batch)
        files_menu.add_command(label='撤销移除', command=self.undo_remove)
        files_menu.add_separator()
        files_menu.add_command(label='开始转换', command=self.start, accelerator='⌘Return' if sys.platform=='darwin' else 'Ctrl+Enter')
        menu.add_cascade(label='文件', menu=files_menu)
        root.configure(menu=menu)
        modifier = 'Command' if sys.platform=='darwin' else 'Control'
        root.bind(f'<{modifier}-o>', lambda e: self.import_photos() if not self.running else None)
        root.bind(f'<{modifier}-Return>', lambda e: self.start())
        root.bind(f'<{modifier}-z>', lambda e: self.undo_remove())
        root.bind(f'<{modifier}-i>', lambda e: self.toggle_batch())
        if sys.platform=='darwin':
            root.createcommand('tk::mac::OpenDocument', lambda *paths: self.add(paths))
            root.createcommand('tk::mac::Quit', self.close)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def button(self, parent, text, kind, command, quiet=False):
        key = (kind, quiet)
        if key not in self.icons:
            self.icons[key] = icon(self.root, kind, MUTED if quiet else INK)
        return ttk.Button(parent, text=' '+text, image=self.icons[key], compound='left', command=command,
                          style='Quiet.TButton' if quiet else 'Retro.TButton')

    def import_photos(self):
        if self.running:
            return 0
        return self.add_files()

    def add_files(self):
        return self.add(filedialog.askopenfilenames(title='选择 Nikon Zf 照片', filetypes=[('Nikon RAW', '*.nef *.NEF')]))

    def add(self, paths):
        if self.running:
            self.status.set('转换中，请稍候')
            return 0
        if paths is None:
            return self.import_photos()
        found = collect(paths)
        if found and self.start_button.result is not None:
            self.clear()
        if found:
            self._discard_undo()
            self.card.hide()
            if self.new_batch_pending:
                self.film.label_number = f'{randbelow(1000000):06}'
                self.film.label_date = datetime.now().strftime('%Y.%m.%d')
                self.new_batch_pending = False
                self.batch_label.set(self.film.label_number,self.film.label_date)
        added = 0
        for path in found:
            if path not in self.files:
                self.files.append(path)
                self.next_token += 1
                self.film.append(path, self.next_token)
                self.thumbnails.put((path, self.next_token))
                added += 1
        self.count.set(f'{len(self.files):02d} 张照片')
        self._update_label()
        if paths:
            self.status.set('' if found else '没有找到 NEF 文件。')
        return added or (len(found) if found else 0)

    def thumbnail_worker(self):
        while not self.closed.is_set():
            task = self.thumbnails.get()
            if task is None:
                return
            while self.thumbnail_pause.is_set():
                if self.closed.wait(.1):
                    return
            path, token = task
            try:
                image = load_thumbnail(path, self.film.IMAGE)
            except Exception:
                image = None  # A failed preview never prevents RAW conversion.
            if not self.closed.is_set():
                self.events.put(('thumbnail', str(path), token, image))

    def _update_label(self):
        if self.files or self.batch_records:
            self.batch_label.place(x=22,y=9)
        else:
            self.batch_label.place_forget()

    def _discard_undo(self):
        self.undo_snapshot = None
        self.undo_button.place_forget()

    def remove(self):
        if self.running:
            return
        keys = self.film.selection()
        if not keys:
            return
        self.card.hide()
        self.undo_snapshot = [(self.film.order.index(key),key,dict(self.film.records[key]),
                               self.details.get(key)) for key in keys]
        for key in keys:
            self.files.remove(Path(key))
            self.details.pop(key, None)
        self.film.remove(keys)
        self.count.set(f'{len(self.files):02d} 张照片')
        self.status.set(f'已移出 {len(keys)} 张 · 可撤销')
        self.undo_button.place(x=346,y=8)
        self._update_label()

    def undo_remove(self):
        if self.running or not self.undo_snapshot:
            return
        restored = []
        for index,key,record,detail in self.undo_snapshot:
            self.next_token += 1
            record['token'] = self.next_token
            record['draw_height'] = None
            self.film.records[key] = record
            self.film.order.insert(index,key)
            self.files.insert(index,Path(key))
            if detail is not None:
                self.details[key] = detail
            self.thumbnails.put((Path(key),self.next_token))
            restored.append(key)
        self.film.selected = set(restored)
        self.film.anchor = restored[0]
        self.film.reveal(restored[0])
        self.film.redraw()
        self.count.set(f'{len(self.files):02d} 张照片')
        self.status.set('')
        self._discard_undo()
        self._update_label()

    def clear(self):
        if self.running:
            return
        had_batch = bool(self.files or self.batch_records)
        self.film.selected = set(self.film.order)
        self.remove()
        self._discard_undo()
        self.card.hide()
        self.batch_records = self.batch_output = None
        self.new_batch_pending = self.new_batch_pending or had_batch
        self.film.anchor = None
        self.film.xview_moveto(0)
        self.start_button.reset()
        self.status.set('')
        self._update_label()

    def _records(self):
        if self.batch_records is not None:
            return list(self.batch_records.values())
        return [dict(key=key,state=self.film.records[key]['state'],detail=self.details.get(key,''))
                for key in self.film.order]

    def toggle_batch(self):
        if self.card.visible:
            self.card.hide()
        else:
            self.show_batch()

    def show_batch(self):
        self.card_mode = 'batch'
        selected = self.film.selection()
        self.card.show_batch(self.film.label_number,self.film.label_date,self._records(),
                             self.batch_output or self.output.get(),
                             '转换中' if self.running else self.start_button.result or '待转换',
                             selected[0] if selected else None)

    def locate_photo(self, key):
        self.card.hide()
        if key not in self.film.records:
            self.status.set('该照片已移出队列')
            return
        self.film.selected = {key}
        self.film.anchor = key
        self.film.reveal(key)
        self.film.redraw()
        self.film.focus_set()

    def choose_output(self):
        if self.running:
            return
        path = filedialog.askdirectory(title='选择输出文件夹')
        if path:
            self.output.set(path)

    def open_item(self, path):
        try:
            open_path(path)
        except OSError as error:
            messagebox.showerror('无法打开', str(error))

    def reveal_output(self):
        path = Path(self.output.get()).expanduser()
        if path.is_dir():
            self.open_item(path)
        else:
            self.status.set('转换时将创建输出目录')

    def show_detail(self, key=None, *, from_batch=False):
        selected = self.film.selection()
        key = key or (selected[0] if selected else None)
        record = next((r for r in self._records() if r['key']==key),None)
        if record:
            self.card_mode = key
            self.detail_from_batch = from_batch
            self.card.show_detail(record,self.film.label_number,self.show_batch if from_batch else None)

    def _refresh_card(self):
        if not self.card.visible:
            return
        # Retain reading position and keyboard focus as actual work arrives.
        scroll = self.card.scroll_position()
        focus = self.root.focus_get()
        if self.card_mode == 'batch':
            self.show_batch()
        else:
            self.show_detail(self.card_mode,from_batch=self.detail_from_batch)
        self.card.restore_scroll(scroll)
        if focus is not None and focus.winfo_exists():
            focus.focus_set()

    def lock(self, on):
        self.running = on
        self.film.locked = on
        (self.thumbnail_pause.set if on else self.thumbnail_pause.clear)()
        for widget in [self.output_button, self.start_button, self.clear_button, self.import_button]:
            widget.configure(state='disabled' if on else 'normal')
        self.profile.configure(state='disabled' if on else 'readonly')

    def start(self):
        if self.running:
            return
        if not self.files:
            self.status.set('请先添加 NEF 照片。')
            return
        if not self.output.get().strip():
            self.status.set('请选择输出文件夹。')
            return
        self._discard_undo()
        self.card.hide()
        self.batch_output = self.output.get()
        self.batch_records = {str(p):dict(key=str(p),state='waiting',detail='') for p in self.files}
        self.stop.clear()
        self.details = {}
        self.status.set('')
        self.lock(True)
        self.start_button.begin(len(self.files))
        self.film.begin_follow()
        mode = ['auto', 'daylight', 'lowlight'][self.profile.current()]
        lens = 'neutral'  # Never apply donor-template distortion or shading corrections in the GUI.
        files, output = list(self.files), self.output.get()
        for path in files:
            self.film.set_state(str(path), 'waiting')
        threading.Thread(target=self.worker, args=(files, output, mode, lens), daemon=True).start()

    def worker(self, files, output, mode, lens):
        success = fail = 0
        for index, path in enumerate(files):
            if self.stop.is_set():
                break
            self.events.put(('stage', str(path), index / len(files)))
            def stage(message, i=index):
                fraction = STAGE_FRACTIONS.get(message, 0)
                self.events.put(('stage', str(path), (i + fraction) / len(files)))
            try:
                out, report = convert(path, output, mode, lens, status=stage)
                success += 1
                state = 'complete-warning' if report['warnings'] else 'complete'
                self.events.put(('result', str(path), state, str(out)+'\n'+'\n'.join(report['warnings'])))
            except Exception as error:
                fail += 1
                self.events.put(('result', str(path), 'failed', str(error)))
            self.events.put(('progress', index+1, len(files)))
        self.events.put(('done', success, fail, self.stop.is_set()))

    def poll(self):
        try:
            while True:
                item = self.events.get_nowait()
                kind = item[0]
                if kind=='thumbnail':
                    self.film.set_thumbnail(item[1], item[2], item[3])
                    if self.card.visible:
                        self._refresh_card()
                elif kind=='stage':
                    self.film.set_state(item[1], 'processing')
                    if self.batch_records is not None:
                        changed = self.batch_records[item[1]]['state'] != 'processing'
                        self.batch_records[item[1]]['state'] = 'processing'
                        if changed:
                            self._refresh_card()
                    self.film.follow_progress(item[2])
                    self.start_button.update_progress(item[2])
                elif kind=='result':
                    self.film.set_state(item[1], item[2])
                    self.details[item[1]] = item[3]
                    if self.batch_records is not None:
                        self.batch_records[item[1]].update(state=item[2],detail=item[3])
                        self._refresh_card()
                elif kind=='progress':
                    self.film.follow_progress(item[1]/item[2])
                    self.start_button.update_progress(item[1]/item[2], item[1])
                elif kind=='done':
                    self.film.end_follow()
                    self.start_button.finish(item[3], success=item[1], failed=item[2])
                    self.lock(False)
                    self.status.set('')
                    self._refresh_card()
        except queue.Empty:
            pass
        if not self.closed.is_set():
            self.root.after(60, self.poll)

    def request_stop(self):
        if self.running:
            self.stop.set()

    def close(self):
        if self.running:
            self.request_stop()
        else:
            self.closed.set()
            self.thumbnails.put(None)
            self.root.destroy()


def main():
    if len(sys.argv)==3 and sys.argv[1]=='--self-test':
        from diagnostics import self_test
        return self_test(sys.argv[2])
    if '--cli' in sys.argv:
        return cli(sys.argv[sys.argv.index('--cli')+1:])
    root = create_root()
    app = Application(root)
    paths = [p for p in sys.argv[1:] if not p.startswith('-psn_')]
    if paths:
        root.after(100, lambda: app.add(paths))
    root.mainloop()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
