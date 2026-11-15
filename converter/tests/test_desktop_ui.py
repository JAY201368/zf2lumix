"""Interaction contracts for the photo strip, dials and batch timer."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import rawpy
from filmstrip import load_thumbnail


class LCDGlyphTests(unittest.TestCase):
    def test_latin_letters_share_baseline_and_keep_descenders(self):
        from retro_ui import _lcd_glyph
        def rows(character):
            return [y for x,y in _lcd_glyph(character)[1]]
        self.assertEqual(max(rows('H')), max(rows('a')))
        self.assertEqual(max(rows('t')), max(rows('a')))
        self.assertEqual(min(rows('g')), min(rows('a')))
        self.assertGreater(max(rows('g')), max(rows('a')))


class PreviewTests(unittest.TestCase):
    def raw(self, image, flip=0, crop=(0, 0, 400, 200)):
        data = BytesIO()
        image.save(data, format='JPEG')
        raw = MagicMock()
        raw.__enter__.return_value = raw
        left, top, width, height = crop
        raw.sizes = SimpleNamespace(width=400, height=200, left_margin=0, top_margin=0,
            crop_left_margin=left, crop_top_margin=top, crop_width=width, crop_height=height, flip=flip)
        raw.extract_thumb.return_value = SimpleNamespace(format=rawpy.ThumbFormat.JPEG, data=data.getvalue())
        return raw

    def test_preview_applies_camera_crop_and_orientation(self):
        image = Image.new('RGB', (400, 200), 'red')
        raw = self.raw(image, crop=(100, 0, 200, 200))
        with patch('filmstrip.rawpy.imread', return_value=raw):
            self.assertEqual(load_thumbnail('source.NEF').size, (128, 128))
        raw = self.raw(image, flip=6)
        with patch('filmstrip.rawpy.imread', return_value=raw):
            self.assertEqual(load_thumbnail('portrait.NEF').size, (64, 128))
        raw.postprocess.assert_not_called()


@unittest.skipUnless(sys.platform in ('darwin', 'win32') or os.environ.get('DISPLAY'), 'Desktop Tk session required')
class DesktopTests(unittest.TestCase):
    def setUp(self):
        from app import Application, create_root
        self.root = create_root()
        self.root.withdraw()
        self.preview_patch = patch('app.load_thumbnail', return_value=Image.new('RGB', (60, 40), 'red'))
        self.preview_patch.start()
        self.app = Application(self.root)
        self.temp = tempfile.TemporaryDirectory(prefix='NEF 拖放 ')
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.preview_patch.stop)
        self.addCleanup(self.app.close)
        self.paths = []
        for i in range(8):
            path = Path(self.temp.name)/f'照片 {i}.NEF'
            path.write_bytes(b'fixture')
            self.paths.append(path.resolve())

    def pump(self, condition, seconds=3):
        deadline = time.monotonic()+seconds
        while not condition() and time.monotonic()<deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(condition())

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS native window chrome')
    def test_native_controls_remain_with_full_size_wooden_content(self):
        self.root.deiconify()
        self.root.update()
        self.assertTrue(self.app.integrated_titlebar)
        styles = set(self.root.tk.splitlist(self.root.attributes('-stylemask')))
        self.assertTrue({'titled', 'closable', 'miniaturizable', 'resizable',
                         'fullsizecontentview'}.issubset(styles))
        self.assertFalse(self.root.overrideredirect())
        self.assertEqual(self.root.title(), 'Zf2Lumix')
        self.assertEqual(set(self.root.tk.splitlist(self.root.attributes('-buttons'))),
                         {'close', 'miniaturize', 'zoom'})
        from retro_ui import Paper
        paper = next(w for w in self.root.winfo_children() if isinstance(w, Paper))
        self.assertTrue(paper.find_withtag('window-mount'))
        left, top, right, bottom = paper.bbox('window-mount')
        for x,y,w,h in self.root.window_button_bounds():
            self.assertTrue(left < x < x+w < right)
            self.assertTrue(top < y < y+h < bottom)
        self.assertFalse(paper.tag_bind('window-mount', '<Button-1>'))
        self.root.iconify()
        self.root.update()
        self.assertEqual(self.root.state(), 'iconic')
        self.root.deiconify()
        self.root.update()
        self.assertEqual(self.root.state(), 'normal')
        self.assertTrue(self.root.protocol('WM_DELETE_WINDOW'))

    def test_native_drop_parses_tcl_paths_and_rejects_while_locked(self):
        from tkinterdnd2 import COPY, REFUSE_DROP
        event = SimpleNamespace(data=self.root.tk.call('list', *[str(p) for p in self.paths]))
        self.assertEqual(self.app.film._drop(event), COPY)
        self.assertEqual(self.app.files, self.paths)
        self.app.film._drop(event)
        self.assertEqual(len(self.app.files), 8)
        self.app.lock(True)
        self.assertEqual(self.app.film._drop(event), REFUSE_DROP)
        self.app.lock(False)
        bad = Path(self.temp.name)/'ignore.jpg'
        bad.write_bytes(b'fixture')
        self.assertEqual(self.app.film._drop(SimpleNamespace(data=self.root.tk.call('list', str(bad)))), REFUSE_DROP)

    def test_import_key_opens_file_picker_directly_and_background_is_inert(self):
        self.root.deiconify()
        self.root.update()
        self.assertEqual(self.app.import_button.winfo_width(),self.app.clear_button.winfo_width())
        self.assertEqual(self.app.import_button.winfo_height(),self.app.clear_button.winfo_height())
        self.assertFalse(hasattr(self.app,'import_menu'))
        self.assertFalse(hasattr(self.app,'add_folder'))
        with patch('app.filedialog.askopenfilenames',return_value=tuple(map(str,self.paths[:2]))) as picker:
            self.app.import_button.event_generate('<ButtonPress-1>',x=20,y=12)
            self.app.import_button.event_generate('<ButtonRelease-1>',x=20,y=12)
            self.root.update()
            picker.assert_called_once()
        self.assertEqual(self.app.files,self.paths[:2])
        with patch('app.filedialog.askopenfilenames',return_value=()) as picker:
            self.app.film.event_generate('<ButtonPress-1>',x=20,y=10)
            self.root.update()
            picker.assert_not_called()
            self.app.import_photos()
            picker.assert_called_once()
        self.assertEqual(self.app.files,self.paths[:2])
        self.app.lock(True)
        with patch('app.filedialog.askopenfilenames') as picker:
            self.app.import_photos()
            picker.assert_not_called()
        self.app.lock(False)

    def test_only_knob_body_accepts_pointer_changes_and_no_panel_focus_box(self):
        self.root.deiconify()
        self.root.update()
        dial=self.app.profile
        for x,y in [(200,16),(200,55),(400,105),(16,43)]:
            dial.event_generate('<ButtonPress-1>',x=x,y=y)
            dial.event_generate('<B1-Motion>',x=x+44,y=y)
            dial.event_generate('<ButtonRelease-1>',x=x,y=y)
            dial._wheel(SimpleNamespace(x=x,y=y,delta=120))
            self.assertEqual(dial.current(),0)
        dial.event_generate('<ButtonPress-1>',x=80,y=92)
        dial.event_generate('<ButtonRelease-1>',x=80,y=92)
        self.assertEqual(dial.current(),1)
        dial.event_generate('<ButtonPress-1>',x=80,y=92)
        dial.event_generate('<B1-Motion>',x=102,y=92)
        dial.event_generate('<ButtonRelease-1>',x=102,y=92)
        self.assertEqual(dial.current(),2)
        dial._wheel(SimpleNamespace(x=80,y=92,delta=120))
        self.assertEqual(dial.current(),2)  # Mechanical end stop, no wrap.
        dial._focus(True)
        self.assertTrue(dial.find_withtag('knob-focus'))
        for item in dial.find_all():
            if dial.type(item) in ('rectangle','oval'):
                self.assertFalse(dial.itemcget(item,'dash'))

    def test_context_menu_requires_explicit_remove_and_locks_during_conversion(self):
        self.app.add(self.paths[:3])
        self.root.deiconify()
        self.root.update()
        film = self.app.film
        _, image_y, gate_height = film._geometry()
        event = SimpleNamespace(x=80, y=image_y+gate_height/2, state=0)
        film.selected = {str(self.paths[1])}
        with patch.object(film.context_menu,'tk_popup'):
            film._remove_context(event)
        self.assertEqual(len(self.app.files),3)
        self.assertEqual(film.selection(),[str(self.paths[0])])
        film.context_menu.invoke(1)
        self.assertEqual(self.app.files,self.paths[1:3])
        self.app.undo_remove()
        self.assertEqual(self.app.files,self.paths[:3])
        self.app.lock(True)
        with patch.object(film.context_menu,'tk_popup'):
            film._remove_context(event)
        self.assertEqual(film.context_menu.entrycget(1,'state'),'disabled')
        self.app.lock(False)
        film.focus_force()
        self.root.update()
        film.event_generate('<BackSpace>')
        self.root.update()
        self.assertEqual(self.app.files,self.paths[1:3])
        self.assertTrue(all(path.exists() for path in self.paths))

    def test_undo_restores_order_details_and_rejects_stale_previews(self):
        self.app.add(self.paths[:4])
        keys = list(map(str,self.paths[:4]))
        self.app.details[keys[1]] = 'result path'
        token = self.app.film.records[keys[1]]['token']
        self.app.film.selected = {keys[1],keys[3]}
        self.app.remove()
        self.assertEqual(self.app.files,[self.paths[0],self.paths[2]])
        self.app.undo_remove()
        self.assertEqual(self.app.files,self.paths[:4])
        self.assertEqual(self.app.film.order,keys)
        self.assertEqual(self.app.details[keys[1]],'result path')
        self.assertGreater(self.app.film.records[keys[1]]['token'],token)
        self.app.film.set_thumbnail(keys[1],token,None)
        self.assertFalse(self.app.film.records[keys[1]]['preview_error'])
        self.app.film.selected = {keys[0]}
        self.app.remove()
        self.app.clear()
        self.app.undo_remove()
        self.assertEqual(self.app.files,[])

    def test_dial_drag_previews_then_snaps_and_has_end_stops(self):
        dial = self.app.profile
        dial._press(SimpleNamespace(x=80,y=92))
        dial._drag(SimpleNamespace(x=114,y=92))
        self.assertEqual(dial.current(),0)
        self.assertGreater(dial.drag_position,1)
        dial._release(SimpleNamespace(x=114,y=92))
        self.assertEqual(dial.current(),2)
        dial.step(1)
        self.assertEqual(dial.current(),2)
        dial.step(-9)
        self.assertEqual(dial.current(),0)
        dial._press(SimpleNamespace(x=80,y=92))
        dial._drag(SimpleNamespace(x=122,y=92))
        dial.configure(state='disabled')
        dial._release(SimpleNamespace(x=122,y=92))
        self.assertEqual(dial.current(),0)
        self.assertIsNone(dial.drag_position)

    def test_batch_card_actual_results_detail_location_and_new_batch(self):
        self.root.deiconify()
        self.root.geometry('980x800')
        self.app.add(self.paths[:3])
        number = self.app.film.label_number
        def converted(path,*args,**kwargs):
            if path == self.paths[1]:
                raise ValueError('无法读取测试文件')
            return Path(str(path)+'.RW2'), {'warnings': []}
        with patch('app.convert',side_effect=converted):
            self.app.start()
            self.pump(lambda:not self.app.running)
        self.app.show_batch()
        self.root.update()
        text = self.app.card.text.get('1.0','end')
        self.assertIn('成功 2',text)
        self.assertIn('失败 1',text)
        self.assertIn('部分失败',text)
        self.assertTrue(self.app.card.actions.winfo_ismapped())
        self.assertGreaterEqual(self.app.card.actions.winfo_height(),28)
        self.assertLessEqual(self.app.card.winfo_y()+self.app.card.winfo_height(),self.app.card.master.winfo_height())
        card = self.app.card
        hit = self.root.winfo_containing(card.winfo_rootx()+25,card.winfo_rooty()+20)
        self.assertTrue(str(hit).startswith(str(card)), 'Record card must be above the film canvas')
        self.app.show_detail(str(self.paths[1]))
        self.assertIn('无法读取测试文件',self.app.card.text.get('1.0','end'))
        self.app.locate_photo(str(self.paths[1]))
        self.assertFalse(self.app.card.visible)
        self.assertEqual(self.app.film.selection(),[str(self.paths[1])])
        self.app.add([])
        self.assertEqual(self.app.film.label_number,number)
        self.app.add(self.paths[3:4])
        self.assertNotEqual(self.app.film.label_number,number)
        self.assertIsNone(self.app.batch_records)
        self.app.show_batch()
        self.assertNotIn('无法读取测试文件',self.app.card.text.get('1.0','end'))
        self.app.card.hide()
        self.assertFalse(hasattr(self.app,'stop_button'))

    def test_detail_entry_source_survives_refresh_and_stamp_actions(self):
        from batch_card import StampKey
        self.app.add(self.paths[:1])
        key=str(self.paths[0])
        card=self.app.card
        self.app.show_detail(key)
        self.assertEqual(card.actions.winfo_children(),[])
        self.app._refresh_card()
        self.assertEqual(card.actions.winfo_children(),[])
        self.assertTrue(card.text.tag_ranges('hand'))
        self.assertIsInstance(card.close_button,StampKey)
        self.app.show_batch()
        action_range=card.text.tag_ranges('action-0-查看详情')
        self.assertEqual(card.text.get(*action_range),'  查看详情  ')
        detail_button=next(child for child in card.actions.winfo_children()
                           if getattr(child,'text',None)=='查看详情')
        detail_button.command()
        self.assertEqual([child.text for child in card.actions.winfo_children()],['返回记录','定位照片'])
        self.app._refresh_card()
        self.assertEqual([child.text for child in card.actions.winfo_children()],['返回记录','定位照片'])
        card.actions.winfo_children()[0].command()
        self.assertEqual(self.app.card_mode,'batch')
        self.app.show_detail(key)
        self.assertEqual(card.actions.winfo_children(),[])

    def test_card_close_repaints_underlay_and_restores_strip_input(self):
        self.app.add(self.paths[:1])
        self.root.deiconify()
        self.root.update()
        exposed = {}
        for canvas in (self.app.film, self.app.film_scroll):
            canvas.bind('<Expose>', lambda event, c=canvas:
                        exposed.setdefault(c, []).append((event.width, event.height)), add='+')
        for show in (self.app.show_batch, lambda: self.app.show_detail(str(self.paths[0]))):
            show()
            self.root.update()
            exposed.clear()
            button = self.app.card.close_button
            button.event_generate('<ButtonPress-1>', x=32, y=14)
            button.event_generate('<ButtonRelease-1>', x=32, y=14)
            self.root.update()
            self.assertFalse(self.app.card.visible)
            self.assertFalse(self.app.card.winfo_ismapped())
            # Mapping checks alone miss macOS's stale Canvas backing pixels.
            for canvas in (self.app.film, self.app.film_scroll):
                self.assertIn((canvas.winfo_width(), canvas.winfo_height()),
                              exposed.get(canvas, []))
            film = self.app.film
            _, image_y, gate_height = film._geometry()
            film.event_generate('<ButtonPress-1>', x=80, y=int(image_y+gate_height/2))
            film.event_generate('<ButtonRelease-1>', x=80, y=int(image_y+gate_height/2))
            self.root.update()
            self.assertEqual(film.selection(), [str(self.paths[0])])

    def test_edge_lettering_and_photos_share_scroll_coordinates(self):
        self.app.add(self.paths)
        self.root.deiconify()
        self.pump(lambda: self.app.film.records[str(self.paths[0])]['photo'] is not None)
        film = self.app.film
        def item(tag, key):
            return next(i for i in film.find_withtag(tag) if key in film.gettags(i))
        key = str(self.paths[0])
        photo = item('photo', key)
        edge = item('edge-name', key)
        before_photo = film.coords(photo)[0]-film.canvasx(0)
        before_edge = film.coords(edge)[0]-film.canvasx(0)
        film.xview_scroll(2, 'units')
        self.root.update()
        after_photo = film.coords(item('photo', key))[0]-film.canvasx(0)
        after_edge = film.coords(item('edge-name', key))[0]-film.canvasx(0)
        self.assertLess(after_photo, before_photo)
        self.assertEqual(after_photo-before_photo, after_edge-before_edge)

    def test_wheel_and_high_resolution_axes_scroll_without_keyboard_focus(self):
        self.app.add(self.paths)
        self.root.deiconify()
        self.root.update()
        film = self.app.film
        self.app.profile.focus_force()
        for sequence in ('<MouseWheel>', '<Shift-MouseWheel>'):
            film.xview_moveto(.25)
            before = film.canvasx(0)
            film.event_generate(sequence, delta=-120, x=80, y=80)
            self.root.update()
            self.assertGreater(film.canvasx(0), before)
            film.event_generate(sequence, delta=120, x=80, y=80)
            self.root.update()
            self.assertAlmostEqual(film.canvasx(0), before, delta=1)
        if film.bind('<TouchpadScroll>'):
            for dx,dy in ((-37,0),(37,0),(0,-37),(0,37),(-37,-12)):
                film.xview_moveto(.25)
                before = film.canvasx(0)
                film.event_generate('<TouchpadScroll>', delta=(dx << 16) | (dy & 0xffff), x=80, y=80)
                self.root.update()
                expected = -(dx if abs(dx)>abs(dy) else dy)
                self.assertAlmostEqual(film.canvasx(0)-before, expected, delta=1)
        film._scroll_pixels(-100000)
        self.assertEqual(film.canvasx(0), 0)
        film._scroll_pixels(100000)
        self.assertAlmostEqual(film.xview()[1], 1, places=3)

    def test_film_follows_actual_progress_smoothly_and_manual_scroll_interrupts(self):
        self.app.add(self.paths)
        self.root.deiconify()
        self.root.update()
        film = self.app.film
        film.xview_moveto(0)
        film.begin_follow()
        film.follow_progress(.5)
        target = film._motion_target
        self.assertGreater(target, 0)
        self.assertEqual(film.canvasx(0), 0)  # No immediate jump.
        self.pump(lambda: 0 < film.canvasx(0) < target)
        self.pump(lambda: film._motion_job is None)
        self.assertAlmostEqual(film.canvasx(0), target, delta=1)
        # No timer invents conversion progress while the worker is busy.
        self.assertEqual(film._follow_fraction, .5)
        self.assertIsNone(film._motion_job)
        film.follow_progress(.8)
        film._scroll_pixels(-50)
        self.assertIsNone(film._motion_job)
        self.assertIsNone(film._motion_target)
        film.follow_progress(.9)
        self.assertIsNotNone(film._motion_job)
        film.end_follow()
        self.pump(lambda: film._motion_job is None)
        stopped_position = film.canvasx(0)
        film.follow_progress(1)
        self.assertEqual(film.canvasx(0), stopped_position)
        film.begin_follow()
        self.assertIsNotNone(film._motion_job)
        self.app.clear()
        self.assertFalse(film.following)
        self.assertIsNone(film._motion_job)
        self.root.update()
        self.assertEqual(film.canvasx(0), 0)

    def test_console_removals_and_lcd_bindings(self):
        self.assertFalse(hasattr(self.app, 'stop_button'))
        self.assertFalse(hasattr(self.app, 'out_entry'))
        self.assertIs(self.app.count_display.variable, self.app.count)
        self.assertIs(self.app.output_display.variable, self.app.output)
        self.assertIs(self.app.status_display.variable, self.app.readout)
        self.app.output.set('/tmp/新输出')
        self.assertEqual(self.app.output_display.itemcget(
            self.app.output_display.find_withtag('lcd-value')[0], 'text'), '/tmp/新输出')
        self.root.deiconify()
        self.root.geometry('980x800')
        self.root.update()
        self.assertTrue(self.app.start_button.winfo_ismapped())
        self.assertEqual(self.app.film_scroll.winfo_height(),12)
        self.assertEqual(self.app.output_button.winfo_width(),self.app.reveal_button.winfo_width())
        self.assertEqual(self.app.output_button.winfo_height(),self.app.reveal_button.winfo_height())
        self.assertEqual(self.app.start_button.winfo_height(), self.app.start_button.winfo_reqheight())
        bottom = self.app.start_button.winfo_rooty()+self.app.start_button.winfo_height()
        self.assertLessEqual(bottom, self.root.winfo_rooty()+self.root.winfo_height())

    def test_fixed_conversion_key_and_permanent_readout(self):
        self.root.deiconify()
        self.root.geometry('980x800')
        self.root.update()
        button, display = self.app.start_button, self.app.status_display
        self.assertEqual(self.app.readout.get(), 'At the Heart of the Image 📷')
        self.assertTrue(display.find_withtag('lcd-camera'))
        value = display.find_withtag('lcd-value')[0]
        self.assertEqual(display.itemcget(value, 'text'), self.app.readout.get())
        self.assertEqual(display.coords(value)[0], 15)
        self.assertEqual(button.winfo_width(), display.winfo_width())
        self.assertEqual(button.winfo_rootx(), display.winfo_rootx())
        self.assertGreater(display.winfo_rooty(), button.winfo_rooty()+button.winfo_height())
        bounds = (display.winfo_rootx(), display.winfo_rooty(), display.winfo_width(), display.winfo_height())
        for state in ('idle', 'active', 'finished'):
            if state=='active':
                button.begin(7)
                button.update_progress(.5, 3)
                self.assertIn('转换中', self.app.readout.get())
                self.assertIn('3 / 7', self.app.readout.get())
            elif state=='finished':
                button.finish(success=6, failed=1)
                self.assertEqual(self.app.readout.get(), '部分失败 · 成功6 失败1')
            self.assertFalse(button.find_withtag('lcd-dot'))
            self.assertNotIn('\n', self.app.readout.get())
            texts = [button.itemcget(i, 'text') for i in button.find_all() if button.type(i)=='text']
            self.assertEqual(set(texts), {'转换'})
            self.assertTrue(display.find_withtag('lcd-dot'))
            for item in display.find_withtag('lcd-dot'):
                x1, y1, x2, y2 = display.coords(item)
                self.assertTrue(1 < x1 < x2 < display.winfo_width()-2)
                self.assertTrue(1 < y1 < y2 < display.winfo_height()-2)
        self.app.clear()
        self.assertEqual(self.app.readout.get(), 'At the Heart of the Image 📷')
        self.app.status.set('请先添加 NEF 照片。')
        self.root.update()
        self.assertTrue(display.winfo_ismapped())
        self.assertEqual(display.itemcget(display.find_withtag('lcd-value')[0], 'text'), self.app.status.get())
        self.assertLessEqual(display.winfo_rooty()+display.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())
        self.app.status.set('')
        self.root.update()
        self.assertEqual(self.app.readout.get(), 'At the Heart of the Image 📷')
        self.assertTrue(display.winfo_ismapped())
        self.assertEqual(bounds, (display.winfo_rootx(), display.winfo_rooty(), display.winfo_width(), display.winfo_height()))

    def test_clear_removes_entire_queue_without_deleting_sources(self):
        self.app.add(self.paths)
        self.app.details[str(self.paths[0])] = 'previous result'
        self.app.film.selected = {str(self.paths[0])}
        self.app.lock(True)
        self.app.clear()
        self.assertEqual(self.app.files,self.paths)
        self.app.lock(False)
        self.app.clear_button.command()
        self.assertEqual(self.app.files,[])
        self.assertEqual(self.app.film.order,[])
        self.assertEqual(self.app.details,{})
        self.assertEqual(self.app.count.get(),'00 张照片')
        self.assertTrue(all(p.exists() for p in self.paths))
        self.app.add(self.paths[:1])
        self.assertEqual(self.app.files,self.paths[:1])

    def test_portrait_edge_text_aligns_to_landscape_gate(self):
        self.app.add(self.paths[:1])
        self.root.deiconify()
        self.root.update()
        film = self.app.film
        key = str(self.paths[0])
        record = film.records[key]
        record['image'] = Image.new('RGB', (80,160), 'red')
        record['draw_height'] = None
        film._paint()
        def tagged(tag):
            return film.find_withtag(tag)[0]
        gate_left, _, gate_right, _ = film.coords(tagged('gate'))
        self.assertLess(record['photo'].width(), gate_right-gate_left)
        self.assertEqual(film.coords(tagged('edge-number'))[0], gate_left)
        self.assertEqual(film.coords(tagged('edge-name'))[0], gate_right)
        self.assertEqual(film.itemcget(tagged('edge-name'),'text'), self.paths[0].name)
        self.assertEqual(film.itemcget(tagged('edge-number'),'anchor'),'w')
        self.assertEqual(film.itemcget(tagged('edge-name'),'anchor'),'e')
        number_bounds = film.bbox(tagged('edge-number'))
        name_bounds = film.bbox(tagged('edge-name'))
        self.assertLess(number_bounds[2], name_bounds[0])

    def test_dial_selection_dispatch_and_terminal_progress(self):
        self.app.add(self.paths[:1])
        self.app.profile.step(2)
        self.assertEqual(self.app.profile.current(), 2)
        self.assertFalse(hasattr(self.app,'lens'))
        def converted(*args, status):
            status('编码 RW2')
            return Path('result.RW2'), {'warnings': []}
        with patch('app.convert', side_effect=converted) as convert:
            self.app.start()
            self.assertEqual(self.app.profile.control_state, 'disabled')
            self.app.profile.step(1)
            self.assertEqual(self.app.profile.current(), 2)
            self.pump(lambda: not self.app.running)
            self.pump(lambda: self.app.start_button.progress == 1)
            self.assertEqual(convert.call_args.args[2:], ('lowlight', 'neutral'))
        self.assertEqual(self.app.start_button.completed, 1)
        self.assertEqual(self.app.start_button.result, '转换完成')
        self.assertFalse(self.app.film.following)
        self.assertEqual(self.app.film._follow_fraction, 1)
        button = self.app.start_button
        texts = [self.app.status_display.itemcget(i, 'text') for i in self.app.status_display.find_withtag('lcd-value')]
        self.assertIn('转换完成 · 成功1 失败0', texts)
        self.assertNotIn('1 / 1', texts)
        self.assertNotIn('开始转换', texts)
        self.assertEqual(self.app.status.get(), '')
        self.assertEqual(self.app.film.records[str(self.paths[0])]['state'], 'complete')
        self.assertNotIn('编码', self.app.status.get())

    def test_mixed_results_are_shown_together_and_reset_on_retry(self):
        self.app.add(self.paths[:2])
        with patch('app.convert', side_effect=[(Path('result.RW2'), {'warnings': []}), ValueError('fixture failure')]):
            self.app.start()
            self.pump(lambda: not self.app.running)
        button = self.app.start_button
        self.assertEqual(button.result, '部分失败')
        texts = [self.app.status_display.itemcget(i, 'text') for i in self.app.status_display.find_withtag('lcd-value')]
        self.assertIn('部分失败 · 成功1 失败1', texts)
        self.assertEqual(self.app.status.get(), '')
        self.assertEqual(self.app.details[str(self.paths[1])], 'fixture failure')
        with patch('app.convert', return_value=(Path('retry.RW2'), {'warnings': []})):
            self.app.start()
            self.assertIsNone(button.result)
            self.assertEqual((button.success, button.failed), (0, 0))
            self.pump(lambda: not self.app.running)
        self.assertEqual(button.result, '转换完成')
        self.assertEqual((button.success, button.failed), (2, 0))

    def test_clear_resets_finished_button_and_cancels_progress_animation(self):
        self.app.add(self.paths[:1])
        button = self.app.start_button
        button.begin(1)
        button.finish(success=1)
        self.assertIsNotNone(button.job)
        self.app.clear_button.command()
        self.root.update()
        self.assertIsNone(button.result)
        self.assertIsNone(button.job)
        self.assertFalse(button.active)
        self.assertEqual((button.progress, button.target, button.completed, button.total,
                          button.success, button.failed), (0, 0, 0, 0, 0, 0))
        texts = [button.itemcget(i, 'text') for i in button.find_all() if button.type(i)=='text']
        self.assertIn('转换', texts)
        self.assertEqual(self.app.readout.get(), 'At the Heart of the Image 📷')
        self.assertEqual(self.app.files, [])

    def test_import_after_batch_replaces_queue_but_cancel_preserves_it(self):
        from tkinterdnd2 import COPY
        for result in ('转换完成', '部分失败', '转换失败', '已停止'):
            with self.subTest(result=result):
                self.app.clear()
                self.app.add(self.paths[:2])
                button = self.app.start_button
                button.begin(2)
                button.finish(success=2)
                button.result = result
                key = str(self.paths[0])
                old_token = self.app.film.records[key]['token']
                self.app.details[key] = 'previous result'
                with patch('app.filedialog.askopenfilenames', return_value=()):
                    self.app.import_photos()
                self.app.add([Path(self.temp.name)/'invalid.jpg'])
                self.assertEqual(self.app.files, self.paths[:2])
                self.assertEqual(button.result, result)
                # Reimporting an old path must create a fresh record, not be deduplicated away.
                event = SimpleNamespace(data=self.root.tk.call('list', str(self.paths[0]), str(self.paths[2])))
                self.assertEqual(self.app.film._drop(event), COPY)
                self.assertEqual(self.app.files, [self.paths[0], self.paths[2]])
                self.assertEqual(self.app.details, {})
                self.assertIsNone(button.result)
                self.assertEqual(button.total, 0)
                self.assertGreater(self.app.film.records[key]['token'], old_token)
                self.app.film.set_thumbnail(key, old_token, Image.new('RGB', (50, 50)))
                self.assertIsNone(self.app.film.records[key]['image'])
                # Additional imports before conversion still append to this new batch.
                self.app.add(self.paths[3:4])
                self.assertEqual(self.app.files, [self.paths[0], self.paths[2], self.paths[3]])
                self.assertTrue(all(p.exists() for p in self.paths))

    def test_stop_after_current_preserves_unfinished_frames(self):
        self.app.add(self.paths[:2])
        gate = threading.Event()
        entered = threading.Event()
        def converted(*args, status):
            status('映射颜色与生成目标 RAW')
            entered.set()
            gate.wait(2)
            return Path('result.RW2'), {'warnings': []}
        with patch('app.convert', side_effect=converted) as convert:
            self.app.start()
            self.pump(entered.is_set)
            self.app.request_stop()
            gate.set()
            self.pump(lambda: not self.app.running)
            self.assertEqual(convert.call_count, 1)
            self.assertEqual(self.app.start_button.completed, 1)
            self.assertEqual(self.app.start_button.target, .5)
            self.assertEqual(self.app.start_button.result, '已停止')
            self.assertFalse(self.app.film.following)
            self.assertEqual(self.app.film._follow_fraction, .5)
            self.assertEqual(self.app.film.records[str(self.paths[1])]['state'], 'waiting')

    def test_removed_frame_discards_stale_preview_and_scrolls_new_frames(self):
        self.app.add(self.paths)
        key = str(self.paths[0])
        old_token = self.app.film.records[key]['token']
        self.app.film.selected = {key}
        self.app.remove()
        self.app.add([self.paths[0]])
        self.app.film.set_thumbnail(key, old_token, Image.new('RGB', (50, 50)))
        self.assertIsNone(self.app.film.records[key]['photo'])
        self.root.deiconify()
        self.root.update()
        self.app.film.xview_moveto(1)
        self.root.update()
        self.assertGreater(self.app.film.xview()[0], 0)
        self.assertTrue(any(self.app.film.itemcget(item, 'text') == '08'
                            for item in self.app.film.find_all() if self.app.film.type(item) == 'text'))

    def test_failed_conversion_unlocks_and_keeps_error_details(self):
        self.app.add(self.paths[:1])
        with patch('app.convert', side_effect=ValueError('fixture failure')):
            self.app.start()
            self.pump(lambda: not self.app.running)
        self.assertEqual(self.app.details[str(self.paths[0])], 'fixture failure')
        self.assertEqual(self.app.start_button.result, '转换失败')
        self.assertEqual((self.app.start_button.success, self.app.start_button.failed), (0, 1))
        self.assertEqual(self.app.status.get(), '')
        self.assertEqual(self.app.film.records[str(self.paths[0])]['state'], 'failed')
        self.assertEqual(self.app.profile.control_state, 'readonly')


if __name__ == '__main__':
    unittest.main()
