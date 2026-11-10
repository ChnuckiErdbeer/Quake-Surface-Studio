#!/usr/bin/env python3
"""Desktop GUI for conv_layers.py. Requires tkinter and the converter's Python environment."""
import configparser
import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk

from ora_preview import read_ora_layers, load_ora_layer

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'conv_layers.py'
SETTINGS = HERE / 'conv_settings.ini'
SUPPORTED = ('.tga', '.png', '.jpg', '.jpeg', '.bmp', '.pcx', '.webp')

DEFAULTS = {
    'palette': 'quake.pal',
    'ramps': 'neutral,dark_earth,blue_grey,olive_dark,red,ochre,warm_earth,tan,purple_dark,purple_warm,stone,green_grey,yellow_ochre,blue',
    'fullbright_start': '224', 'segments': '180', 'compactness': '10.0',
    'detail': '0.35', 'detail_radius': '1.2', 'coherence': '0.025',
    'material_merge_threshold': '0.055', 'material_luminance_weight': '0.20',
    'material_chroma_limit': '0.075', 'ramp_candidates_per_zone': '5',
    'alpha_threshold': '128', 'color_key_tolerance': '0',
}

class ConverterGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Quake Texture Converter')
        self.geometry('1020x900')
        self.minsize(820, 760)
        self.events = queue.Queue()
        self.vars = {k: tk.StringVar(value=v) for k, v in DEFAULTS.items()}
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.ora_dir_var = tk.StringVar()
        self.fullbright_masks_var = tk.BooleanVar(value=True)
        self.stop_requested = threading.Event()
        self.mode_var = tk.StringVar(value='file')
        self.color_key_enabled = tk.BooleanVar(value=False)
        self.color_key_var = tk.StringVar(value='FF00FF')
        self.layers_var = tk.BooleanVar(value=False)
        self.recursive_var = tk.BooleanVar(value=False)
        self.preview_refs = {'input': None, 'output': None}
        self.preview_enabled = tk.BooleanVar(value=True)
        self.preview_zoom = tk.DoubleVar(value=1.0)
        self.ramp_vars = {}
        self.ora_layers = []
        self.ora_path = None
        self.ora_photo = None
        self.pause_gate = threading.Event(); self.pause_gate.set()
        self.pause_requested = False
        self.completed_files = []
        self.review_index = -1
        self.worker_thread = None
        self.current_options = []
        self.status_var = tk.StringVar(value='Choose an input image or folder to begin.')
        self._load_settings()
        self._build()
        self.after(100, self._poll_events)

    def _load_settings(self):
        cfg = configparser.ConfigParser()
        if SETTINGS.exists():
            cfg.read(SETTINGS, encoding='utf-8')
        if cfg.has_section('conversion'):
            for k in DEFAULTS:
                if k in cfg['conversion']:
                    self.vars[k].set(cfg['conversion'][k])

    def _save_settings(self):
        cfg = configparser.ConfigParser()
        cfg['conversion'] = {k: v.get() for k, v in self.vars.items()}
        SETTINGS.write_text('; Quake texture converter settings\n' + self._config_text(cfg), encoding='utf-8')
        self._log(f'Settings saved to {SETTINGS}')

    @staticmethod
    def _config_text(cfg):
        from io import StringIO
        out = StringIO(); cfg.write(out); return out.getvalue()

    def _build(self):
        root = ttk.Frame(self, padding=12); root.pack(fill='both', expand=True)
        ttk.Label(root, text='Quake Texture Converter', font=('TkDefaultFont', 17, 'bold')).pack(anchor='w')
        ttk.Label(root, text='Convert game textures to the 256-colour Quake palette').pack(anchor='w', pady=(0, 12))

        src = ttk.LabelFrame(root, text='1. Input', padding=10); src.pack(fill='x', pady=5)
        line = ttk.Frame(src); line.pack(fill='x')
        ttk.Entry(line, textvariable=self.input_var).pack(side='left', fill='x', expand=True)
        ttk.Button(line, text='Choose file…', command=self._choose_file).pack(side='left', padx=(6, 0))
        ttk.Button(line, text='Choose folder…', command=self._choose_folder).pack(side='left', padx=(6, 0))
        ttk.Label(src, text='Supported currently: TGA, PNG, JPG, BMP, PCX and WEBP.').pack(anchor='w', pady=(5, 0))

        out = ttk.LabelFrame(root, text='2. Output', padding=10); out.pack(fill='x', pady=5)
        line = ttk.Frame(out); line.pack(fill='x')
        ttk.Entry(line, textvariable=self.output_var).pack(side='left', fill='x', expand=True)
        ttk.Button(line, text='Choose destination…', command=self._choose_output).pack(side='left', padx=(6, 0))
        ttk.Checkbutton(out, text='Also create layered ORA diagnostic project', variable=self.layers_var).pack(anchor='w', pady=(7, 0))
        ora_line = ttk.Frame(out); ora_line.pack(fill='x', pady=(4, 0))
        ttk.Label(ora_line, text='ORA destination (optional):').pack(side='left')
        ttk.Entry(ora_line, textvariable=self.ora_dir_var).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(ora_line, text='Browse…', command=self._choose_ora_dir).pack(side='left')
        ttk.Checkbutton(out, text='Automatically use sibling *_fullbrights.png masks', variable=self.fullbright_masks_var).pack(anchor='w', pady=(5, 0))
        ttk.Checkbutton(out, text='Convert subfolders recursively (preserve folder structure)', variable=self.recursive_var).pack(anchor='w', pady=(4, 0))

        preview = ttk.LabelFrame(root, text='Live preview — source and converted texture', padding=8)
        preview.pack(fill='x', pady=5)
        preview_controls = ttk.Frame(preview); preview_controls.pack(fill='x', pady=(0, 6))
        ttk.Checkbutton(preview_controls, text='Display previews (disable for maximum speed)', variable=self.preview_enabled, command=self._toggle_preview).pack(side='left')
        ttk.Button(preview_controls, text='◀ Previous', command=lambda: self._navigate_preview(-1)).pack(side='right', padx=2)
        ttk.Button(preview_controls, text='Next ▶', command=lambda: self._navigate_preview(1)).pack(side='right', padx=2)
        ttk.Button(preview_controls, text='Reconvert selected', command=self._reconvert_selected).pack(side='right', padx=8)
        ttk.Label(preview_controls, text='Zoom').pack(side='left', padx=(12, 3))
        zoom = ttk.Scale(preview_controls, from_=0.25, to=4.0, variable=self.preview_zoom, command=lambda _v: self._refresh_review())
        zoom.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.preview_status = tk.StringVar(value='No completed files yet')
        ttk.Label(preview_controls, textvariable=self.preview_status).pack(side='left', padx=10)
        previews = ttk.Frame(preview); previews.pack(fill='both', expand=True)
        self.input_preview = ttk.Label(previews, text='Input image\n(not selected)', anchor='center', relief='groove')
        self.input_preview.pack(side='left', fill='both', expand=True, padx=(0, 4), ipady=4)
        self.output_preview = ttk.Label(previews, text='Converted output\n(will appear after conversion)', anchor='center', relief='groove')
        self.output_preview.pack(side='left', fill='both', expand=True, padx=(4, 0), ipady=4)
        ora_bar = ttk.Frame(preview); ora_bar.pack(fill='x', pady=(7, 2))
        ttk.Label(ora_bar, text='ORA layer:').pack(side='left')
        self.ora_layer_var = tk.StringVar(value='(no ORA for selected image)')
        self.ora_layer_combo = ttk.Combobox(ora_bar, textvariable=self.ora_layer_var, state='readonly', width=42)
        self.ora_layer_combo.pack(side='left', padx=6)
        self.ora_layer_combo.bind('<<ComboboxSelected>>', self._show_ora_layer)
        ttk.Button(ora_bar, text='◀', width=3, command=lambda: self._step_ora_layer(-1)).pack(side='left')
        ttk.Button(ora_bar, text='▶', width=3, command=lambda: self._step_ora_layer(1)).pack(side='left', padx=(3, 8))
        self.ora_preview = ttk.Label(preview, text='Pause or review a completed file with ORA export enabled to inspect its layers.', anchor='center', relief='groove')
        self.ora_preview.pack(fill='x', ipady=3)

        trans = ttk.LabelFrame(root, text='3. Transparency', padding=10); trans.pack(fill='x', pady=5)
        row = ttk.Frame(trans); row.pack(fill='x')
        ttk.Label(row, text='Alpha threshold:').pack(side='left')
        ttk.Entry(row, textvariable=self.vars['alpha_threshold'], width=7).pack(side='left', padx=6)
        ttk.Label(row, text='Alpha below this value becomes transparent (0–255).').pack(side='left')
        row = ttk.Frame(trans); row.pack(fill='x', pady=(7, 0))
        ttk.Checkbutton(row, text='Use colour key (only for sources without alpha)', variable=self.color_key_enabled).pack(side='left')
        ttk.Entry(row, textvariable=self.color_key_var, width=9).pack(side='left', padx=6)
        ttk.Button(row, text='Pick…', command=self._pick_color).pack(side='left')
        ttk.Label(row, text='Tolerance:').pack(side='left', padx=(14, 3))
        ttk.Entry(row, textvariable=self.vars['color_key_tolerance'], width=5).pack(side='left')

        settings = ttk.LabelFrame(root, text='4. Conversion settings', padding=8); settings.pack(fill='both', expand=True, pady=5)
        canvas = tk.Canvas(settings, highlightthickness=0, height=190)
        scroll = ttk.Scrollbar(settings, orient='vertical', command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
        fields = [
            ('palette', 'Palette file'), ('ramps', 'Enabled palette ramps (comma-separated)'),
            ('segments', 'SLIC segments'), ('compactness', 'SLIC compactness'),
            ('detail', 'Detail enhancement'), ('detail_radius', 'Detail radius'),
            ('coherence', 'Ramp coherence'), ('material_merge_threshold', 'Material merge threshold'),
            ('material_luminance_weight', 'Material luminance weight'), ('material_chroma_limit', 'Material chroma limit'),
            ('ramp_candidates_per_zone', 'Ramp candidates per zone'), ('fullbright_start', 'Fullbright start index (reserved)'),
        ]
        self.entries = {}
        for i, (key, label) in enumerate(fields):
            ttk.Label(inner, text=label).grid(row=i, column=0, sticky='w', padx=5, pady=3)
            ent = ttk.Entry(inner, textvariable=self.vars[key], width=65 if key == 'ramps' else 22)
            ent.grid(row=i, column=1, sticky='ew', padx=5, pady=3); self.entries[key] = ent
            if key == 'palette':
                ttk.Button(inner, text='Browse…', command=self._choose_palette).grid(row=i, column=2, padx=4)
        inner.columnconfigure(1, weight=1)
        ramp_frame = ttk.LabelFrame(inner, text='Palette ramp families', padding=6)
        ramp_frame.grid(row=len(fields), column=0, columnspan=3, sticky='ew', padx=5, pady=(8, 4))
        ramp_names = ['neutral', 'dark_earth', 'blue_grey', 'olive_dark', 'red', 'ochre', 'warm_earth', 'tan', 'purple_dark', 'purple_warm', 'stone', 'green_grey', 'yellow_ochre', 'blue']
        ramp_colors = {
            'neutral': ['#080808', '#777777', '#eeeeee'], 'dark_earth': ['#18100c', '#70452d', '#c28b5b'],
            'blue_grey': ['#182430', '#526b7c', '#b0c5d2'], 'olive_dark': ['#171b0b', '#58602b', '#a1a35a'],
            'red': ['#250b0b', '#a52c26', '#f08068'], 'ochre': ['#291d0c', '#9a702b', '#e8c16c'],
            'warm_earth': ['#21130d', '#87502e', '#d59a69'], 'tan': ['#292014', '#a18a5e', '#e4d2a0'],
            'purple_dark': ['#170e20', '#59406e', '#a78ac0'], 'purple_warm': ['#25101d', '#8d456d', '#d89ab6'],
            'stone': ['#282828', '#858078', '#d1c9b8'], 'green_grey': ['#101d16', '#526e58', '#a7c0a3'],
            'yellow_ochre': ['#2a2108', '#a58a22', '#f0d56a'], 'blue': ['#08162b', '#235ba1', '#83b9f0']
        }
        current_ramps = {name.strip() for name in self.vars['ramps'].get().split(',') if name.strip()}
        self.ramp_vars = {}
        for i, name in enumerate(ramp_names):
            cell = ttk.Frame(ramp_frame)
            cell.grid(row=i // 4, column=i % 4, sticky='ew', padx=4, pady=3)
            var = tk.BooleanVar(value=name in current_ramps)
            self.ramp_vars[name] = var
            ttk.Checkbutton(cell, text=name.replace('_', ' '), variable=var, command=self._sync_ramps).pack(anchor='w')
            swatch = tk.Canvas(cell, width=112, height=12, highlightthickness=0)
            swatch.pack(anchor='w')
            cols = ramp_colors[name]
            for px in range(112):
                t = px / 111
                seg = t * (len(cols) - 1)
                j = min(int(seg), len(cols) - 2)
                f = seg - j
                a = tuple(int(cols[j][k:k+2], 16) for k in (1, 3, 5))
                b = tuple(int(cols[j+1][k:k+2], 16) for k in (1, 3, 5))
                rgb = tuple(round(a[c] + (b[c] - a[c]) * f) for c in range(3))
                swatch.create_line(px, 0, px, 12, fill='#%02x%02x%02x' % rgb)
        for col in range(4): ramp_frame.columnconfigure(col, weight=1)
        buttons = ttk.Frame(root); buttons.pack(fill='x', pady=(7, 5))
        ttk.Button(buttons, text='Save settings', command=self._save_settings).pack(side='left')
        self.pause_button = ttk.Button(buttons, text='Pause after current file', command=self._toggle_pause, state='disabled')
        self.pause_button.pack(side='right', padx=6)
        self.stop_button = ttk.Button(buttons, text='Stop after current file', command=self._stop, state='disabled')
        self.stop_button.pack(side='right', padx=6)
        self.convert_button = ttk.Button(buttons, text='Convert', command=self._start)
        self.convert_button.pack(side='right', ipadx=25, ipady=7)
        self.progress = ttk.Progressbar(root, mode='indeterminate'); self.progress.pack(fill='x', pady=4)
        ttk.Label(root, textvariable=self.status_var).pack(anchor='w')
        logframe = ttk.LabelFrame(root, text='Conversion log', padding=6); logframe.pack(fill='both', expand=True, pady=(5, 0))
        self.log = tk.Text(logframe, height=9, wrap='word', state='disabled')
        sb = ttk.Scrollbar(logframe, command=self.log.yview); self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')

    def _sync_ramps(self):
        selected = [name for name, var in self.ramp_vars.items() if var.get()]
        if not selected:
            # Keep at least one ramp enabled; the converter requires a usable family.
            first = next(iter(self.ramp_vars))
            self.ramp_vars[first].set(True)
            selected = [first]
        self.vars['ramps'].set(','.join(selected))

    def _refresh_review(self):
        if self.completed_files and self.review_index >= 0:
            self._display_review(self.review_index)

    def _refresh_ora_for_review(self):
        self.ora_layers = []
        self.ora_path = None
        self.ora_photo = None
        if not self.completed_files or self.review_index < 0:
            self.ora_layer_combo['values'] = []
            self.ora_layer_var.set('(no ORA for selected image)')
            self.ora_preview.configure(image='', text='No ORA layer selected.')
            return
        _source, output = self.completed_files[self.review_index]
        output_path = Path(output)
        candidates = [output_path.with_suffix('.ora')]
        if self.ora_dir_var.get().strip():
            ora_root = Path(self.ora_dir_var.get()).expanduser()
            source_root = Path(self.input_var.get()).expanduser()
            if source_root.is_dir() and self.recursive_var.get():
                try:
                    ora_relative = Path(_source).relative_to(source_root).with_suffix('.ora')
                except ValueError:
                    ora_relative = output_path.with_suffix('.ora').name
            else:
                ora_relative = output_path.with_suffix('.ora').name
            candidates.insert(0, ora_root / ora_relative)
        ora = next((p for p in candidates if p.is_file()), None)
        if ora is None:
            self.ora_layer_combo['values'] = []
            self.ora_layer_var.set('(ORA not found)')
            self.ora_preview.configure(image='', text='No ORA project was created for this image.')
            return
        try:
            _w, _h, self.ora_layers = read_ora_layers(ora)
            self.ora_path = ora
            names = [layer['name'] for layer in self.ora_layers]
            self.ora_layer_combo['values'] = names
            visible = next((i for i, layer in enumerate(self.ora_layers) if layer['visible']), 0)
            self.ora_layer_combo.current(visible)
            self._render_ora_layer(visible)
        except Exception as exc:
            self.ora_layer_combo['values'] = []
            self.ora_layer_var.set('(ORA read error)')
            self.ora_preview.configure(image='', text=f'Cannot read ORA: {exc}')

    def _render_ora_layer(self, index):
        if not self.ora_path or not self.ora_layers:
            return
        index = max(0, min(index, len(self.ora_layers) - 1))
        try:
            image = load_ora_layer(self.ora_path, self.ora_layers[index])
            image.thumbnail((940, 280), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.ora_preview.configure(image=photo, text='')
            self.ora_photo = photo
            self.ora_layer_combo.current(index)
        except Exception as exc:
            self.ora_preview.configure(image='', text=f'Cannot preview ORA layer: {exc}')

    def _show_ora_layer(self, _event=None):
        index = self.ora_layer_combo.current()
        if index >= 0: self._render_ora_layer(index)

    def _step_ora_layer(self, step):
        if self.ora_layers:
            index = self.ora_layer_combo.current()
            self._render_ora_layer((max(0, index) + step) % len(self.ora_layers))

    def _toggle_preview(self):
        if not self.preview_enabled.get():
            self._clear_preview('input', 'Preview disabled')
            self._clear_preview('output', 'Preview disabled')
            self.preview_status.set('Preview disabled')
        elif self.completed_files:
            self._display_review(self.review_index if self.review_index >= 0 else len(self.completed_files)-1)

    def _display_review(self, index):
        if not self.completed_files or not self.preview_enabled.get():
            return
        index = max(0, min(index, len(self.completed_files)-1))
        self.review_index = index
        source, output = self.completed_files[index]
        self._show_preview('input', source)
        self._show_preview('output', output)
        self.preview_status.set(f'Completed file {index+1} / {len(self.completed_files)}')
        self._refresh_ora_for_review()

    def _navigate_preview(self, step):
        if self.completed_files:
            self._display_review((self.review_index if self.review_index >= 0 else len(self.completed_files)-1) + step)

    def _toggle_pause(self):
        if self.pause_gate.is_set():
            self.pause_gate.clear()
            self.pause_requested = True
            self.pause_button.configure(text='Resume conversion')
            self.status_var.set('Pause requested — current file will finish first.')
        else:
            # Capture any settings edited while paused; the worker uses them for subsequent files.
            self._save_settings_silent()
            palette = Path(self.vars['palette'].get()).expanduser()
            if not palette.is_absolute(): palette = HERE / palette
            self.current_options = ['--settings', str(SETTINGS), '--palette', str(palette), '--alpha-threshold', self.vars['alpha_threshold'].get(), '--color-key-tolerance', self.vars['color_key_tolerance'].get()]
            if self.layers_var.get(): self.current_options.append('--layers')
            if self.ora_dir_var.get().strip(): self.current_options += ['--ora-dir', self.ora_dir_var.get().strip()]
            if not self.fullbright_masks_var.get(): self.current_options.append('--no-fullbright-masks')
            if self.color_key_enabled.get(): self.current_options += ['--color-key', self.color_key_var.get().upper()]
            self.pause_gate.set()
            self.pause_requested = False
            self.pause_button.configure(text='Pause after current file')
            self.status_var.set('Conversion resumed.')

    def _reconvert_selected(self):
        if not self.completed_files or self.review_index < 0:
            messagebox.showinfo('Nothing selected', 'Convert at least one file, then select it in the preview.')
            return
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning('Conversion running', 'Pause and finish the current batch before reconverting a reviewed file.')
            return
        source, output = self.completed_files[self.review_index]
        self._launch_conversion(Path(source), Path(output), recursive=False)

    def _clear_preview(self, which, text):
        widget = self.input_preview if which == 'input' else self.output_preview
        widget.configure(image='', text=text)
        self.preview_refs[which] = None

    def _show_preview(self, which, path):
        widget = self.input_preview if which == 'input' else self.output_preview
        try:
            with Image.open(path) as source:
                zoom = max(0.25, min(4.0, float(self.preview_zoom.get())))
                im = source.convert('RGBA')
                # Keep the preview widget a fixed size. Zooming in crops around
                # the image centre; zooming out leaves a neutral margin.
                scaled_size = (max(1, int(470 * zoom)), max(1, int(230 * zoom)))
                im.thumbnail(scaled_size, Image.Resampling.LANCZOS)
                canvas = Image.new('RGBA', (470, 230), (52, 52, 52, 255))
                if zoom >= 1.0:
                    left = max(0, (im.width - 470) // 2)
                    top = max(0, (im.height - 230) // 2)
                    crop = im.crop((left, top, min(im.width, left + 470), min(im.height, top + 230)))
                    canvas.alpha_composite(crop, ((470 - crop.width) // 2, (230 - crop.height) // 2))
                else:
                    canvas.alpha_composite(im, ((470 - im.width) // 2, (230 - im.height) // 2))
                photo = ImageTk.PhotoImage(canvas)
            widget.configure(image=photo, text='')
            self.preview_refs[which] = photo
        except Exception as exc:
            widget.configure(image='', text=f'Cannot preview image\n{exc}')
            self.preview_refs[which] = None

    def _choose_file(self):
        p = filedialog.askopenfilename(filetypes=[('Supported images', ' '.join('*'+x for x in SUPPORTED)), ('All files', '*')])
        if p:
            self.input_var.set(p)
            self.output_var.set(str(Path(p).with_name(Path(p).stem + '_quake.png')))
            self._show_preview('input', p)
            self._clear_preview('output', 'Converted output\n(not converted yet)')

    def _choose_folder(self):
        p = filedialog.askdirectory()
        if p:
            self.input_var.set(p); self.output_var.set(str(Path(p) / 'converted'))
            self._clear_preview('input', 'Input image\nshown when processing starts')
            self._clear_preview('output', 'Converted output\nshown after each file')

    def _choose_output(self):
        src = Path(self.input_var.get()) if self.input_var.get() else None
        if src and src.is_dir():
            p = filedialog.askdirectory(initialdir=self.output_var.get() or str(src))
        else:
            p = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG image', '*.png')])
        if p: self.output_var.set(p)

    def _choose_ora_dir(self):
        p = filedialog.askdirectory(initialdir=self.ora_dir_var.get() or self.output_var.get() or str(HERE))
        if p: self.ora_dir_var.set(p)

    def _stop(self):
        self.stop_requested.set()
        self.pause_gate.set()
        self.status_var.set('Stop requested — finishing the current file…')

    def _choose_palette(self):
        p = filedialog.askopenfilename(filetypes=[('JASC palette', '*.pal'), ('All files', '*')])
        if p: self.vars['palette'].set(p)

    def _pick_color(self):
        initial = self.color_key_var.get().lstrip('#')
        try: initial = '#' + initial
        except Exception: initial = '#ff00ff'
        chosen = colorchooser.askcolor(color=initial, parent=self)[1]
        if chosen: self.color_key_var.set(chosen.lstrip('#').upper())

    def _log(self, message):
        self.log.configure(state='normal'); self.log.insert('end', message + '\n'); self.log.see('end'); self.log.configure(state='disabled')

    def _start(self):
        src = Path(self.input_var.get()).expanduser()
        if not src.exists():
            messagebox.showerror('Input required', 'Choose an existing input image or folder.'); return
        dst_text = self.output_var.get().strip()
        if not dst_text:
            messagebox.showerror('Output required', 'Choose an output file or folder.'); return
        self._launch_conversion(src, Path(dst_text).expanduser(), bool(self.recursive_var.get()))

    def _launch_conversion(self, src, dst, recursive):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning('Conversion running', 'Wait for the current conversion to finish or resume it first.'); return
        if not SCRIPT.exists():
            messagebox.showerror('Converter missing', f'Cannot find {SCRIPT}'); return
        palette = Path(self.vars['palette'].get()).expanduser()
        if not palette.is_absolute(): palette = HERE / palette
        if not palette.exists():
            messagebox.showerror('Palette missing', f'Cannot find palette file:\n{palette}'); return
        try:
            for key, var in self.vars.items():
                if key not in ('palette', 'ramps'): float(var.get())
            threshold = int(self.vars['alpha_threshold'].get()); tol = int(self.vars['color_key_tolerance'].get())
            if not 0 <= threshold <= 255 or not 0 <= tol <= 255: raise ValueError('Alpha threshold and colour-key tolerance must be 0–255.')
            if self.color_key_enabled.get() and (len(self.color_key_var.get()) != 6 or any(c not in '0123456789abcdefABCDEF' for c in self.color_key_var.get())): raise ValueError('Colour key must be six hexadecimal digits, e.g. FF00FF.')
        except ValueError as e:
            messagebox.showerror('Invalid setting', str(e)); return
        self._save_settings_silent()
        options = ['--settings', str(SETTINGS), '--palette', str(palette), '--alpha-threshold', self.vars['alpha_threshold'].get(), '--color-key-tolerance', self.vars['color_key_tolerance'].get()]
        if self.layers_var.get(): options.append('--layers')
        if self.ora_dir_var.get().strip(): options += ['--ora-dir', self.ora_dir_var.get().strip()]
        if not self.fullbright_masks_var.get(): options.append('--no-fullbright-masks')
        if self.color_key_enabled.get(): options += ['--color-key', self.color_key_var.get().upper()]
        self.current_options = list(options)
        self.convert_button.configure(state='disabled')
        self.pause_button.configure(state='normal', text='Pause after current file')
        self.pause_gate.set(); self.pause_requested = False; self.stop_requested.clear()
        self.stop_button.configure(state='normal')
        self.progress.configure(mode='indeterminate'); self.progress.start(10)
        self.status_var.set('Preparing conversion…')
        self.worker_thread = threading.Thread(target=self._worker, args=(src, dst, options, recursive), daemon=True)
        self.worker_thread.start()

    def _save_settings_silent(self):
        cfg = configparser.ConfigParser(); cfg['conversion'] = {k: v.get() for k, v in self.vars.items()}
        SETTINGS.write_text('; Quake texture converter settings\n' + self._config_text(cfg), encoding='utf-8')

    def _worker(self, src, dst, options, recursive):
        try:
            if src.is_dir():
                supported = set(SUPPORTED)
                iterator = src.rglob('*') if recursive else src.iterdir()
                files = sorted(p for p in iterator if p.is_file() and p.suffix.lower() in supported
                               and dst not in p.parents)
                if not files:
                    raise RuntimeError('No supported images found in the selected folder.')
                dst.mkdir(parents=True, exist_ok=True)
            else:
                files = [src]
                dst.parent.mkdir(parents=True, exist_ok=True)
            self.events.put(('total', len(files)))
            failures = 0
            for index, image_path in enumerate(files, 1):
                self.pause_gate.wait()
                if self.stop_requested.is_set():
                    self.events.put(('stopped', (failures, len(files), index-1)))
                    return
                if src.is_dir():
                    rel = image_path.relative_to(src) if recursive else Path(image_path.name)
                    out_path = (dst / rel).with_suffix('.png')
                else:
                    out_path = dst
                out_path.parent.mkdir(parents=True, exist_ok=True)
                self.events.put(('current', (index, len(files), str(image_path))))
                per_file_options = list(self.current_options)
                ora_base = None
                if '--ora-dir' in per_file_options:
                    ora_i = per_file_options.index('--ora-dir')
                    if ora_i + 1 < len(per_file_options): ora_base = Path(per_file_options[ora_i + 1]).expanduser()
                    del per_file_options[ora_i:ora_i + 2]
                if ora_base is not None:
                    ora_rel_parent = image_path.relative_to(src).parent if src.is_dir() and recursive else Path('.')
                    per_file_options += ['--ora-dir', str(ora_base / ora_rel_parent)]
                cmd = [sys.executable, str(SCRIPT), str(image_path), str(out_path), *per_file_options]
                self.events.put(('log', '$ ' + ' '.join(cmd)))
                proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in proc.stdout:
                    self.events.put(('log', line.rstrip()))
                code = proc.wait()
                if code == 0:
                    self.events.put(('completed', (str(image_path), str(out_path))))
                else:
                    failures += 1
                    self.events.put(('log', f'FAILED ({code}): {image_path}'))
                self.events.put(('item_done', (index, len(files), failures)))
            self.events.put(('done', (failures, len(files))))
        except Exception as exc:
            self.events.put(('error', str(exc)))

    def _poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log': self._log(value)
                elif kind == 'total':
                    self.progress.stop(); self.progress.configure(mode='determinate', maximum=value, value=0)
                    self.status_var.set(f'0 / {value} images')
                elif kind == 'current':
                    index, total, path = value
                    self.status_var.set(f'Processing {index} / {total}: {Path(path).name}')
                elif kind == 'completed':
                    source, output = value
                    self.completed_files.append((source, output))
                    if self.preview_enabled.get(): self._display_review(len(self.completed_files)-1)
                elif kind == 'item_done':
                    index, total, failures = value
                    self.progress.configure(value=index)
                    self.status_var.set(f'{index} / {total} images — {failures} failed' + (' — paused after this file' if not self.pause_gate.is_set() else ''))
                elif kind == 'done':
                    failures, total = value
                    self.progress.stop(); self.convert_button.configure(state='normal'); self.pause_button.configure(state='disabled', text='Pause after current file'); self.stop_button.configure(state='disabled')
                    self.status_var.set(f'Finished: {total - failures} succeeded, {failures} failed.')
                elif kind == 'stopped':
                    failures, total, done = value
                    self.progress.stop(); self.convert_button.configure(state='normal'); self.pause_button.configure(state='disabled', text='Pause after current file'); self.stop_button.configure(state='disabled')
                    self.status_var.set(f'Stopped: {done} of {total} files processed; {failures} failed.')
                elif kind == 'error':
                    self.progress.stop(); self.convert_button.configure(state='normal'); self.pause_button.configure(state='disabled'); self.stop_button.configure(state='disabled'); self.status_var.set('Conversion failed.'); self._log('ERROR: ' + value)
        except queue.Empty: pass
        self.after(100, self._poll_events)

if __name__ == '__main__':
    app = ConverterGUI(); app.mainloop()
