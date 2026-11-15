"""Presentation-only components for the photographic desktop interface."""

import math
import random
import ctypes
import sys
from pathlib import Path
from functools import lru_cache
import tkinter as tk
from tkinter import font as tkfont, ttk

from PIL import Image, ImageDraw, ImageTk, ImageFont, ImageFilter, ImageColor


PAPER = '#eee6d5'
CARD = '#363c39'
WOOD = '#a65e45'
PRINT = '#d6d0b8'
LCD_BG = '#172b26'
LCD_INK = '#c4e4ad'
INK = '#302f29'
MUTED = '#7c7567'
LINE = '#cfc3ad'
ACCENT = '#995343'
FILM = '#373932'


def register_fonts():
    """Load the bundled OFL fonts for this process, without installing them."""
    paths = sorted((Path(__file__).resolve().parent / 'assets' / 'fonts').glob('*.ttf'))
    try:
        if sys.platform == 'darwin':
            cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
            ct = ctypes.CDLL('/System/Library/Frameworks/CoreText.framework/CoreText')
            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            for path in paths:
                encoded = str(path.resolve()).encode('utf-8')
                url = cf.CFURLCreateFromFileSystemRepresentation(None, encoded, len(encoded), False)
                if url:
                    try:
                        ct.CTFontManagerRegisterFontsForURL(url, 1, None)
                    finally:
                        cf.CFRelease(url)
        elif sys.platform == 'win32':
            add_font = ctypes.windll.gdi32.AddFontResourceExW
            add_font.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
            add_font.restype = ctypes.c_int
            for path in paths:
                add_font(str(path), 0x10, None)  # FR_PRIVATE: this process only.
    except (OSError, AttributeError):
        # The theme below uses installed native fallbacks if registration fails.
        pass


def setup_theme(root):
    register_fonts()
    available = set(tkfont.families(root))
    def pick(*names):
        return next((name for name in names if name in available), 'TkDefaultFont')
    fonts = {
        'body': pick('Heiti SC', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC'),
        'display': pick('DIN Alternate', 'Bahnschrift', 'Arial Narrow', 'Helvetica'),
        'script': pick('Snell Roundhand', 'Apple Chancery', 'URW Chancery L', 'Georgia'),
        'mono': pick('Menlo', 'Consolas', 'DejaVu Sans Mono', 'Courier New'),
    }
    root._retro_fonts = fonts
    root.configure(bg=PAPER)
    root.option_add('*Font', (fonts['body'], 13))
    root.option_add('*TCombobox*Listbox.background', CARD)
    root.option_add('*TCombobox*Listbox.foreground', INK)
    root.option_add('*TCombobox*Listbox.selectBackground', ACCENT)
    root.option_add('*TCombobox*Listbox.selectForeground', CARD)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=PAPER, foreground=INK, font=(fonts['body'], 13))
    style.configure('Paper.TFrame', background=PAPER)
    style.configure('Card.TFrame', background=CARD)
    style.configure('Paper.TLabel', background=PAPER)
    style.configure('Muted.TLabel', background=PAPER, foreground=MUTED)
    style.configure('Card.TLabel', background=CARD)
    style.configure('Caption.TLabel', background=CARD, foreground=MUTED, font=(fonts['mono'], 10))
    style.configure('Retro.TButton', background=CARD, foreground=INK, bordercolor=LINE,
                    lightcolor=CARD, darkcolor=CARD, relief='flat', padding=(12, 7),
                    font=(fonts['body'], 13), focusthickness=1, focuscolor=ACCENT)
    style.map('Retro.TButton', background=[('disabled', PAPER), ('pressed', '#d5c8b0'), ('active', '#e5dac6')],
              foreground=[('disabled', '#a59c8b')], bordercolor=[('focus', ACCENT)])
    style.configure('Quiet.TButton', background=PAPER, bordercolor=PAPER,
                    lightcolor=PAPER, darkcolor=PAPER, padding=(9, 6))
    style.map('Quiet.TButton', background=[('active', '#e1d5bf'), ('pressed', '#d5c8b0')])
    style.configure('Retro.TEntry', fieldbackground='#fffaf0', foreground=INK,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=6)
    style.map('Retro.TEntry', bordercolor=[('focus', ACCENT)], fieldbackground=[('disabled', PAPER)])
    style.configure('Retro.TCombobox', fieldbackground='#fffaf0', background='#e5dac6',
                    foreground=INK, arrowcolor=INK, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, padding=6)
    style.map('Retro.TCombobox', fieldbackground=[('readonly', '#fffaf0'), ('disabled', PAPER)],
              foreground=[('disabled', '#a59c8b')], bordercolor=[('focus', ACCENT)])
    return fonts


class TypeLabel(ttk.Label):
    """Native font rendering keeps outlines sharp at the display's resolution."""
    def __init__(self, master, text, size=13, color=INK, **kwargs):
        kwargs.setdefault('foreground', color)
        kwargs.setdefault('font', (master.winfo_toplevel()._retro_fonts['body'], size))
        super().__init__(master, text=text, **kwargs)


def material(canvas, bounds, kind, color=CARD, pressed=False, tags=()):
    """Antialiased surface only; native text, hit areas and layout stay intact.

    Keep one image per surface slot, so animated controls do not retain frames.
    Supersample the bevels, then match Tk's logical image dimensions.
    """
    x, y, r, b = bounds
    w, h = max(1, round(r-x)), max(1, round(b-y))
    key = (kind, tuple(bounds))
    signature = (w, h, kind, color, pressed)
    cache = getattr(canvas, '_material_images', {})
    if key not in cache or cache[key][0] != signature:
        im = _material_bitmap(*signature)
        photo = ImageTk.PhotoImage(im, master=canvas)
        # Tk Canvas images use physical pixels even on Retina, so retain smooth
        # supersampled edges while matching the original logical dimensions.
        cache[key] = (signature, photo)
        if len(cache) > 12:
            cache = {key: cache[key]}
        canvas._material_images = cache
    return canvas.create_image(x, y, image=cache[key][1], anchor='nw', tags=tags)


@lru_cache(maxsize=48)
def _material_bitmap(w, h, kind, color, pressed):
    scale = 3
    im = Image.new('RGBA', (w*scale, h*scale))
    draw = ImageDraw.Draw(im)
    def shape(box, fill, radius=4):
        box = tuple(round(v*scale) for v in box)
        if kind == 'dial':
            draw.ellipse(box, fill=fill)
        else:
            draw.rounded_rectangle(box, radius=radius*scale, fill=fill)
    if kind == 'lcd':
        layers = [(0, '#25372b'), (1, '#18271e'), (2, '#14231b'),
                  (3, '#14271f'), (4, LCD_BG)]
    elif kind == 'key':
        layers = [(0, '#152019'), (1, '#222e23'), (3, '#848a75'),
                  (4, '#ecebd5'), (5, '#b2b79f')]
    elif kind == 'dial':
        layers = [(0, '#19231d'), (1, '#747d68'), (2, '#b8bda5'),
                  (3, '#4e5948'), (7, '#1e2b23'), (9, '#838d73'), (10, '#424e3d')]
    else:
        layers = [(0, '#704933'), (1, '#202b23'), (2, '#263229'),
                  (3, color)]
    for inset, fill in layers:
        shape((inset, inset, w-1-inset, h-1-inset), fill)
    inset = layers[-1][0]+1
    base = ImageColor.getrgb(LCD_BG if kind == 'lcd' else '#cdd0b7' if kind == 'key' else '#475441' if kind == 'dial' else color)
    surface = Image.new('RGBA', im.size)
    pixels = []
    rng = random.Random(71)
    for yy in range(h):
        for xx in range(w):
            if kind == 'lcd':
                delta = 2*math.sin(math.pi*yy/max(1,h))-12*math.exp(-max(0,yy-inset)/4)-5*math.exp(-max(0,xx-inset)/5)
            elif kind == 'key':
                delta = 12-25*yy/max(1,h) - (12 if pressed else 0)
            elif kind == 'dial':
                delta = 12-17*yy/max(1,h)-8*xx/max(1,w)
            else:
                # Fade to the body's exact flat color before the child frame.
                edge = min(xx, yy, w-1-xx, h-1-yy)
                delta = (-15*math.exp(-max(0,yy-inset)/3.5)
                         -8*math.exp(-max(0,xx-inset)/4))*max(0,1-edge/18)
            noise = rng.uniform(-.6,.6)
            pixels.append(tuple(max(0,min(255,round(v+delta+noise))) for v in base)+(255,))
    low = Image.new('RGBA',(w,h)); low.putdata(pixels)
    surface = low.resize(im.size, Image.Resampling.BICUBIC)
    mask = Image.new('L',im.size)
    md = ImageDraw.Draw(mask)
    box = (inset*scale,inset*scale,(w-1-inset)*scale,(h-1-inset)*scale)
    if box[2] > box[0] and box[3] > box[1]:
        if kind == 'dial': md.ellipse(box,fill=255)
        else: md.rounded_rectangle(box,radius=2*scale,fill=255)
    im.paste(surface,(0,0),mask)
    if kind in ('panel', 'lcd'):
        # Light catches only the lower/right lip of an inset opening; a
        # symmetric bright outline reads as a raised metal frame instead.
        rim = Image.new('RGBA', im.size)
        rd = ImageDraw.Draw(rim)
        rd.rounded_rectangle((0,0,(w-1)*scale,(h-1)*scale),radius=4*scale,
                             outline='#c08c64' if kind == 'panel' else '#65765a',width=scale)
        reveal = Image.new('L',im.size)
        reveal_draw = ImageDraw.Draw(reveal)
        reveal_draw.rectangle((0,(h-2)*scale,w*scale,h*scale),fill=230)
        reveal_draw.rectangle(((w-2)*scale,h*scale//2,w*scale,h*scale),fill=110)
        reveal = Image.composite(rim.getchannel('A'),Image.new('L',im.size),reveal)
        im.paste(rim,(0,0),reveal)
    return im.resize((w,h),Image.Resampling.LANCZOS)


def draw_dial(canvas, angle, disabled=False, center=(58, 67), output_size=92):
    """Draw the detailed dial artwork at a caller-selected center and size."""
    scale = 4
    size = 82
    im = Image.new('RGBA', (size*scale, size*scale))
    shadow = Image.new('RGBA', im.size)
    sd = ImageDraw.Draw(shadow)
    def box(radius, dx=0, dy=0):
        return tuple(round(v*scale) for v in
                     (41-radius+dx,39-radius+dy,41+radius+dx,39+radius+dy))
    sd.ellipse(box(33,-1,3),fill=(8,16,10,145))
    im = shadow.filter(ImageFilter.GaussianBlur(2.4*scale))
    d = ImageDraw.Draw(im)
    d.ellipse(box(34),fill='#263225',outline='#697557',width=scale//2)
    d.ellipse(box(31),fill='#1d2a20',outline='#303e2c',width=scale//2)
    # Fine radial grip: each tooth has a light shoulder and a dark groove.
    for degrees in range(0,360,6):
        a = math.radians(degrees)
        lighting = (math.cos(a+2.2)+1)/2
        tone = tuple(round(v+lighting*17) for v in (91,105,76))
        def point(radius, offset=0):
            return ((41+radius*math.cos(a+offset))*scale,
                    (39+radius*math.sin(a+offset))*scale)
        d.line((point(26.2),point(30.3)),fill=tone,width=scale)
        d.line((point(26.2,.035),point(30.3,.035)),fill='#34412e',width=scale//2)
    d.ellipse(box(26.3),fill='#839071',outline='#1a291e',width=scale//2)
    d.ellipse(box(25.5),fill='#32412f')
    face = Image.new('RGBA',im.size)
    fd = ImageDraw.Draw(face)
    for yy in range(14*scale,65*scale):
        t=(yy/scale-14)/51
        shade=round(10-18*t)
        base=(75,87,68) if not disabled else (65,75,60)
        fd.line((15*scale,yy,67*scale,yy),fill=tuple(v+shade for v in base),width=1)
    mask=Image.new('L',im.size)
    ImageDraw.Draw(mask).ellipse(box(24.8),fill=255)
    im.paste(face,(0,0),mask)
    d=ImageDraw.Draw(im)
    d.arc(box(25.2),190,300,fill='#9aa187',width=scale//2)
    d.arc(box(25.2),15,135,fill='#273725',width=scale//2)
    # A short ivory inlay near the rim, with a recessed seat and a lit edge.
    ux,uy=math.cos(angle),math.sin(angle)
    vx,vy=-uy,ux
    def bar(start,end,half,dx=0,dy=0):
        return [((41+r*ux+sign*half*vx+dx)*scale,
                 (39+r*uy+sign*half*vy+dy)*scale)
                for r,sign in ((start,-1),(end,-1),(end,1),(start,1))]
    d.polygon(bar(11.5,24,1.7,0,.7),fill='#263123')
    d.polygon(bar(12,23.7,1.25),fill='#dcd3aa' if not disabled else '#9a9e86')
    d.line((bar(12,23.7,1.25)[0],bar(12,23.7,1.25)[1]),fill='#f1e7bd',width=scale//2)
    canvas._dial_image=ImageTk.PhotoImage(im.resize((output_size,output_size),Image.Resampling.LANCZOS),master=canvas)
    cx,cy=center
    canvas.create_image(cx-output_size*41/82,cy-output_size*39/82,
                        image=canvas._dial_image,anchor='nw',tags='dial-surface')


def paper_texture(master):
    """Restrained red maple, with broad tonal movement and very little grain."""
    rng = random.Random(35)
    image = Image.new('RGB', (768, 768))
    pixels = []
    for y in range(768):
        band = 1.7*math.sin(2*math.pi*y/768)
        for x in range(768):
            flow = 2*math.pi*y/768 + .12*math.sin(2*math.pi*x/768)
            grain = 1.2*math.sin(38*flow) + .7*math.sin(91*flow) + .4*math.sin(193*flow)
            shade = round(band + grain + rng.uniform(-.7,.7))
            pixels.append((166+shade, 94+shade, 69+shade))
    image.putdata(pixels)
    return ImageTk.PhotoImage(image, master=master)


class Paper(tk.Canvas):
    def __init__(self, master):
        super().__init__(master, bg=WOOD, highlightthickness=0, bd=0)
        self.tile = paper_texture(self)
        self.bind('<Configure>', self._paint)

    def _paint(self, event):
        self.delete('grain')
        for x in range(0, event.width, 768):
            for y in range(0, event.height, 768):
                self.create_image(x, y, image=self.tile, anchor='nw', tags='grain')
        w, h = event.width, event.height
        for inset, light, dark in [(3, '#c38b69', '#704732'), (5, '#b87c59', '#83503a'), (7, '#ae7052', '#92573e')]:
            self.create_line(inset,h-inset,inset,inset,w-inset,inset,fill=light,tags='grain',width=2)
            self.create_line(w-inset,inset,w-inset,h-inset,inset,h-inset,fill=dark,tags='grain',width=2)
        script = self.winfo_toplevel()._retro_fonts['script']
        face = (script,36,'bold')
        metrics = tkfont.Font(self,font=face)
        words = ('Zf','to','Lumix')
        widths = [metrics.measure(word) for word in words]
        gaps = (26,12,0)
        left = (w-sum(widths)-sum(gaps))/2
        for word,width,gap in zip(words,widths,gaps):
            self.create_text(left+.5,48,text=word,anchor='w',font=face,fill='#c68a65',tags='grain')
            self.create_text(left,47,text=word,anchor='w',font=face,fill='#653b2c',tags='grain')
            left += width+gap
        self.tag_lower('grain')
        self._window_control_mount()

    def _window_control_mount(self):
        """Subtle routed wooden seats behind the actual AppKit buttons."""
        self.delete('window-mount')
        root = self.winfo_toplevel()
        bounds = getattr(root, 'window_button_bounds', lambda: [])()
        if not bounds or root.attributes('-fullscreen'):
            return
        tag = 'window-mount'
        for x,y,w,h in bounds:
            # A hairline wood bevel and a narrow inner shadow, with no shared plate.
            self.create_oval(x-1.5,y-1,x+w+1.5,y+h+2,
                             fill='#8e503a',outline='',tags=tag)
            self.create_arc(x-1.5,y-1,x+w+1.5,y+h+2,start=205,extent=140,
                            style='arc',outline='#c18a66',width=.7,tags=tag)
            self.create_oval(x-.5,y-.5,x+w+.5,y+h+.5,
                             fill='#593b2c',outline='#80513a',width=.6,tags=tag)


@lru_cache(maxsize=512)
def _lcd_glyph(character):
    """An 18-row character cell, restricted to whole on/off electrodes."""
    if character == '📷':
        pixels = (
            '0000011110000000',
            '0000100001000000',
            '0011111111111100',
            '0100000000000010',
            '0100001111001010',
            '0100010000100010',
            '0100100000010010',
            '0100100110010010',
            '0100100110010010',
            '0100100000010010',
            '0100010000100010',
            '0100001111000010',
            '0100000000000010',
            '0011111111111100',
        )
        return 16, tuple((x,y+2) for y,row in enumerate(pixels)
                         for x,pixel in enumerate(row) if pixel=='1')
    ascii_cell = ord(character) < 128
    width = 9 if ascii_cell else 16
    bundled = Path(__file__).resolve().parent/'assets/fonts'
    candidates = ([bundled/'VT323-Regular.ttf', Path('/System/Library/Fonts/Menlo.ttc'), Path('C:/Windows/Fonts/consola.ttf')]
                  if ascii_cell else [Path('/System/Library/Fonts/STHeiti Medium.ttc'), Path('C:/Windows/Fonts/msyh.ttc'), bundled/'LXGWWenKaiMono-Regular.ttf'])
    font_path = next((path for path in candidates if path.is_file()), None)
    font_size = (20 if font_path and font_path.name == 'VT323-Regular.ttf' else 14) if ascii_cell else 16
    face = ImageFont.truetype(str(font_path),font_size) if font_path else ImageFont.load_default()
    mask = Image.new('L',(width,18))
    draw=ImageDraw.Draw(mask)
    bounds=draw.textbbox((0,0),character,font=face)
    glyph_w,glyph_h=bounds[2]-bounds[0],bounds[3]-bounds[1]
    left=(width-glyph_w)//2-bounds[0]
    if ascii_cell:
        # A shared baseline preserves the relationship between capitals,
        # lowercase letters and descenders instead of centering each glyph.
        draw.text((left,14),character,font=face,fill=255,anchor='ls')
    else:
        draw.text((left,(18-glyph_h)//2-bounds[1]),character,font=face,fill=255)
    return width,tuple((x,y) for y in range(18) for x in range(width) if mask.getpixel((x,y))>=84)


def lcd_text_width(text,size):
    return sum(_lcd_glyph(c)[0]+1 for c in text)*max(1,round(size/12))


def panel_text(canvas,x,y,text,fonts,size=12,anchor='w',fill=PRINT,dark=False,**kwargs):
    """Paint-filled engraving with a shallow, directional cut into the surface."""
    face=(fonts['body'],size)
    canvas.create_text(x,y+1,text=text,anchor=anchor,font=face,
                       fill='#e7e5cc' if dark else '#6c7763',**kwargs)
    canvas.create_text(x,y-1,text=text,anchor=anchor,font=face,
                       fill='#727763' if dark else '#172219',**kwargs)
    # Muted inlay leaves the cut's lower light edge visible without a white halo.
    ink = fill if dark else '#%02x%02x%02x' % tuple(round(v*.85) for v in ImageColor.getrgb(fill))
    return canvas.create_text(x,y,text=text,anchor=anchor,font=face,
                              fill=ink,**kwargs)



class PanelLabel(tk.Canvas):
    def __init__(self,master,text,fonts,size=12):
        face=tkfont.Font(master,font=(fonts['body'],size))
        super().__init__(master,width=face.measure(text)+4,height=36,bg=CARD,bd=0,highlightthickness=0)
        panel_text(self,2,18,text,fonts,size,fill='#bfc2ab')


def lcd(canvas, bounds, text, fonts, size=13, anchor='w', disabled=False, text_inset=14):
    """Inset glass and discrete square electrodes, confined to LCD windows."""
    x,y,r,b = bounds
    material(canvas,bounds,'lcd')
    step=max(1,round(size/12))
    lines=text.split('\n')
    line_height=24*step
    top=(y+b-(18*step+line_height*(len(lines)-1)))/2
    color='#657b62' if disabled else '#c4e4ad'
    halo = Image.new('RGBA', (max(1,round(r-x)), max(1,round(b-y))))
    halo_draw = ImageDraw.Draw(halo)
    halo_item = canvas.create_image(x,y,anchor='nw')
    for line in lines:
        left=(x+r-lcd_text_width(line,size))/2 if anchor=='center' else x+text_inset
        # Keep semantic text for introspection without smooth text over electrodes.
        canvas.create_text(left,top,text=line,state='hidden',tags='lcd-value')
        for character in line:
            width,dots=_lcd_glyph(character)
            for col,row in dots:
                px,py=left+col*step,top+row*step
                if px+step<r-8:
                    if not disabled:
                        halo_draw.rectangle((px-x,py-y,px-x+step,py-y+step),fill=(175,221,140,145))
                    tags = ('lcd-dot', 'lcd-camera') if character=='📷' else ('lcd-dot',)
                    canvas.create_rectangle(px,py,px+step,py+step,fill=color,outline='',tags=tags)
            left+=(width+1)*step
        top+=line_height
    canvas._lcd_halo = ImageTk.PhotoImage(halo.filter(ImageFilter.GaussianBlur(1.7)),master=canvas)
    canvas.itemconfigure(halo_item,image=canvas._lcd_halo)



class LCD(tk.Canvas):
    def __init__(self, master, variable, fonts, width=300, height=48, bg=CARD, size=13, anchor='w'):
        super().__init__(master,width=width,height=height,bg=bg,highlightthickness=0,bd=0)
        self.variable,self.fonts,self.size = variable,fonts,size
        self.anchor = anchor
        self.trace = variable.trace_add('write',self._draw)
        self.bind('<Configure>',self._draw)
        self._draw()

    def _draw(self,*args):
        self.delete('all')
        w = self.winfo_width() if self.winfo_width()>1 else int(self.cget('width'))
        h = int(self.cget('height'))
        lines=[]
        for text in self.variable.get().split('\n'):
            while lcd_text_width(text,self.size)>w-30 and len(text)>4:
                text='…'+text[2:]
            lines.append(text)
        lcd(self,(1,1,w-2,h-2),'\n'.join(lines),self.fonts,self.size,anchor=self.anchor)

    def destroy(self):
        self.variable.trace_remove('write',self.trace)
        super().destroy()


class ConsolePlate(tk.Canvas):
    def __init__(self,master,color=CARD,inset=22,top_inset=None,**kwargs):
        super().__init__(master,bg=WOOD,bd=0,highlightthickness=0,**kwargs)
        self.color,self.inset=color,inset
        self.top_inset=inset if top_inset is None else top_inset
        self.body=tk.Frame(self,bg=color)
        self.window=self.create_window(inset,self.top_inset,window=self.body,anchor='nw')
        self.bind('<Configure>',self._draw)

    def _draw(self,event):
        self.delete('surface')
        w,h=event.width,event.height
        material(self,(0,0,w,h),'panel',self.color,tags='surface')
        for x in (12,w-17):
            for y in (12,h-17):
                self.create_oval(x-4,y-4,x+4,y+4,fill='#707964',outline='#202c22',tags='surface')
                self.create_arc(x-3,y-3,x+3,y+3,start=35,extent=150,style='arc',outline='#a6ac90',tags='surface')
                self.create_line(x-2,y+3,x+2,y-1,fill='#949d80',tags='surface')
                self.create_line(x-2,y+2,x+2,y-2,fill='#343d34',tags='surface')
        self.itemconfigure(self.window,width=max(1,w-2*self.inset-4),height=max(1,h-self.inset-self.top_inset-4))
        self.tag_lower('surface')


class PhysicalKey(tk.Canvas):
    def __init__(self,master,text,command,fonts,width=130,bg=CARD,height=48):
        super().__init__(master,width=width,height=height,bg=bg,bd=0,highlightthickness=0,takefocus=True,cursor='hand2')
        self.text,self.command,self.fonts=text,command,fonts
        self.control_state='normal'
        self.pressed=self.focused=False
        self.bind('<ButtonPress-1>',self._press)
        self.bind('<ButtonRelease-1>',self._release)
        self.bind('<Leave>',lambda e:self._set(False))
        self.bind('<space>',self._keyboard)
        self.bind('<Return>',self._keyboard)
        self.bind('<FocusIn>',lambda e:self._focus(True))
        self.bind('<FocusOut>',lambda e:self._focus(False))
        self._draw()

    def configure(self,cnf=None,**kwargs):
        options=dict(cnf or {},**kwargs)
        if 'state' in options:
            self.control_state=options.pop('state')
            self.pressed=False
            self._draw()
        if options:
            return super().configure(**options)

    def _focus(self,on):
        self.focused=on
        self._draw()

    def _set(self,on):
        self.pressed=on
        self._draw()

    def _press(self,event):
        if self.control_state!='disabled':
            self.focus_set()
            self._set(True)

    def _release(self,event):
        active=self.pressed and 0<=event.x<self.winfo_width() and 0<=event.y<self.winfo_height()
        self._set(False)
        if active and self.control_state!='disabled':
            self.command()

    def _keyboard(self,event):
        if self.control_state!='disabled':
            self.command()
        return 'break'

    def _draw(self):
        self.delete('all')
        w=int(self.cget('width')); d=2 if self.pressed else 0
        ratio=int(self.cget('height'))/48
        material(self,(2,(3+d)*ratio,w-2,45*ratio),'key',pressed=self.pressed)
        panel_text(self,w/2,22+d,self.text,self.fonts,10 if int(self.cget('height'))<40 else 12,anchor='center',
                   fill='#8a8c7c' if self.control_state=='disabled' else '#3a4437',dark=True)
        if self.focused:
            self.create_rectangle(9,9+d,w-9,35+d,outline='#7f7259',dash=(2,3))
        for item in self.find_all():
            if self.type(item) != 'image':
                self.scale(item,0,0,1,ratio)


def icon(master, kind, color=INK, size=22):
    """Draw camera-inspired pictograms at 3x resolution for smooth edges."""
    scale = 3
    im = Image.new('RGBA', (size * scale, size * scale))
    d = ImageDraw.Draw(im)
    def line(points, width=1.5, fill=color):
        d.line([(int(x * scale), int(y * scale)) for x, y in points], fill=fill,
               width=round(width * scale), joint='curve')
    def box(bounds, radius=1, fill=None, outline=color, width=1.4):
        d.rounded_rectangle(tuple(round(v * scale) for v in bounds), radius=round(radius * scale),
                            fill=fill, outline=outline, width=round(width * scale))
    def circle(bounds, fill=None, outline=color, width=1.4):
        d.ellipse(tuple(round(v * scale) for v in bounds), fill=fill, outline=outline, width=round(width * scale))
    if kind == 'camera':
        box((2, 6, 20, 19), 2)
        line([(6, 6), (8, 3), (13, 3), (15, 6)])
        circle((8, 9, 15, 16)); line([(17, 9), (18, 9)])
    elif kind == 'album':
        box((4, 3, 19, 20), 1.5); line([(7, 3), (7, 20)])
        box((10, 7, 16, 14), .5); line([(2, 7), (5, 7)]); line([(2, 16), (5, 16)])
    elif kind == 'folder':
        line([(2, 7), (2, 4), (9, 4), (11, 7), (19, 7), (19, 9)])
        line([(2, 8), (20, 8), (17, 19), (3, 19), (2, 8)])
    elif kind == 'remove':
        box((3, 3, 19, 19), 1); line([(7, 11), (15, 11)])
    elif kind == 'guide':
        box((3, 3, 18, 19), 1); line([(7, 3), (7, 19)])
        line([(10, 8), (15, 8)]); line([(10, 12), (15, 12)])
    elif kind == 'dial':
        circle((3, 3, 19, 19)); circle((8, 8, 14, 14))
        for a in range(0, 360, 45):
            r = math.radians(a)
            line([(11 + 6 * math.cos(r), 11 + 6 * math.sin(r)),
                  (11 + 8 * math.cos(r), 11 + 8 * math.sin(r))], 1)
        line([(11, 11), (15, 6)], 1.7)
    elif kind == 'stop':
        circle((2, 2, 20, 20)); box((8, 7, 10, 15), 0, fill=color, outline=None)
        box((13, 7, 15, 15), 0, fill=color, outline=None)
    elif kind == 'film':
        box((2, 3, 20, 19), 1)
        for x in (5, 10, 15):
            box((x, 4, x + 2, 6), 0, fill=color, outline=None)
            box((x, 16, x + 2, 18), 0, fill=color, outline=None)
        line([(3, 8), (19, 8)], 1); line([(3, 14), (19, 14)], 1)
    return ImageTk.PhotoImage(im.resize((size, size), Image.Resampling.LANCZOS), master=master)

