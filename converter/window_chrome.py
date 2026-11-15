"""macOS native window controls over the wooden content surface."""
import ctypes
import platform
import sys
import tkinter as tk


class _Rect(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double),
                ('width', ctypes.c_double), ('height', ctypes.c_double)]


def integrated_titlebar(root):
    """Keep native traffic lights and resizing, with no separate title strip."""
    if sys.platform != 'darwin':
        return False
    try:
        styles = tuple(root.tk.splitlist(root.attributes('-stylemask')))
    except tk.TclError:
        # Tk 8.6 does not expose full-size content views; retain native chrome.
        return False
    root.attributes('-stylemask', (*styles, 'fullsizecontentview'))
    root.update_idletasks()
    # Keep the window's name for the Window menu and accessibility, but hide
    # its native title text. Only the main window is changed, never dialogs.
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

    def send(receiver, selector, result=ctypes.c_void_p, args=(), values=()):
        if result is _Rect and platform.machine() == 'x86_64':
            # Intel uses the separate Objective-C entry point for large structs.
            output = _Rect()
            stret = ctypes.cast(objc.objc_msgSend_stret, ctypes.c_void_p).value
            method = ctypes.CFUNCTYPE(None, ctypes.POINTER(_Rect), ctypes.c_void_p,
                                      ctypes.c_void_p, *args)(stret)
            method(ctypes.byref(output), receiver, objc.sel_registerName(selector.encode()), *values)
            return output
        method = ctypes.CFUNCTYPE(result, ctypes.c_void_p, ctypes.c_void_p, *args)(address)
        return method(receiver, objc.sel_registerName(selector.encode()), *values)

    app = send(objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    windows = send(app, 'windows')
    for index in range(send(windows, 'count', ctypes.c_ulong)):
        window = send(windows, 'objectAtIndex:', args=(ctypes.c_ulong,), values=(index,))
        title = send(send(window, 'title'), 'UTF8String', ctypes.c_char_p)
        if title and title.decode('utf-8') == root.title():
            send(window, 'setTitleVisibility:', None, (ctypes.c_long,), (1,))
            def button_bounds():
                content = send(window, 'contentView')
                frame = send(content, 'frame', _Rect)
                flipped = send(content, 'isFlipped', ctypes.c_bool)
                bounds = []
                for kind in (0, 1, 2):  # Close, minimize, zoom; retain native hit areas.
                    button = send(window, 'standardWindowButton:', args=(ctypes.c_ulong,), values=(kind,))
                    if not button or send(button, 'isHidden', ctypes.c_bool):
                        continue
                    rect = send(button, 'bounds', _Rect)
                    rect = send(button, 'convertRect:toView:', _Rect,
                                (_Rect, ctypes.c_void_p), (rect, content))
                    y = rect.y if flipped else frame.height-rect.y-rect.height
                    bounds.append((rect.x, y, rect.width, rect.height))
                return bounds
            # The controls keep their top-left offsets during resizing. Cache
            # them while the NSWindow is alive: Tk can repaint child canvases
            # during teardown, after AppKit has already released the window.
            bounds = tuple(button_bounds())
            root.window_button_bounds = lambda: bounds
            return True
    return False
