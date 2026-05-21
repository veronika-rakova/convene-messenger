import os
import time
import tkinter as tk
import customtkinter as ctk
import numpy as np
from tkinter import messagebox
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class InteractiveScheduler:
    def __init__(self, schedules_data, my_nick, container, on_grid_update=None):
        self.my_nick = str(my_nick).strip().lower()
        self.schedules = schedules_data
        self.num_people = len(self.schedules)
        self.visible_count = min(self.num_people, 4)
        self.on_grid_update = on_grid_update

        self.current_scroll = 0
        self.mouse_pos = None
        self.last_hovered_axis = None

        is_dark = ctk.get_appearance_mode() == "Dark"
        self.REF_BG = "#2B2B2B" if is_dark else "#F0F0F0"
        self.REF_GRID = "#1F1F1F" if is_dark else "#FFFFFF"
        self.REF_LINES = "#333333" if is_dark else "#DDDDDD"
        self.REF_HEADER = "#3B3B3B" if is_dark else "#E0E0E0"
        self.ACCENT_BLUE = "#3B8ED0" if is_dark else "#1F6AA5"
        self.TEXT_DIM = "#888888" if is_dark else "#555555"

        self.fig = Figure(figsize=(8, 10), dpi=100, facecolor=self.REF_BG, constrained_layout=False)
        self.fig.subplots_adjust(left=0.1, right=0.95, top=0.90, bottom=0.08, hspace=0.6)

        self.canvas = FigureCanvasTkAgg(self.fig, master=container)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

        btn_style = {"fg_color": self.REF_GRID, "text_color": self.ACCENT_BLUE,
                     "font": ctk.CTkFont(size=12, weight="bold")}
        self.controls_frame = ctk.CTkFrame(container, fg_color="transparent", height=40)
        self.controls_frame.pack(fill="x", padx=10, pady=(5, 0), before=self.canvas_widget)

        ctk.CTkButton(self.controls_frame, text="ОЧИСТИТЬ (R)", command=self.action_reset, **btn_style).pack(
            side="left", padx=2)
        ctk.CTkButton(self.controls_frame, text="ДЕНЬ (D)", command=self.action_fill_day, **btn_style).pack(side="left",
                                                                                                            padx=2)
        ctk.CTkButton(self.controls_frame, text="НЕДЕЛЯ (F)", command=self.action_fill_week, **btn_style).pack(
            side="left", padx=2)

        ctk.CTkButton(self.controls_frame, text="💾 СОХРАНИТЬ", command=self.action_save_matches, fg_color="#2B5278",
                      text_color="white", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=10)

        ctk.CTkLabel(self.controls_frame, text="ЛКМ: изменить своё | Наведите курсор для хоткеев",
                     text_color=self.TEXT_DIM,
                     font=ctk.CTkFont(size=10)).pack(side="right", padx=10)

        self.axes = self.fig.subplots(self.visible_count + 1, 1)
        if not isinstance(self.axes, (list, np.ndarray)): self.axes = np.array([self.axes])

        self.imgs = []
        for i in range(self.visible_count + 1):
            ax = self.axes[i]
            ax.set_facecolor(self.REF_GRID)
            asp = 1.2
            if i < self.visible_count:
                img = ax.imshow(np.zeros((7, 24)), aspect=asp, cmap='Blues', vmin=0, vmax=1, interpolation='nearest')
                self.imgs.append(img)
            else:
                self.res_img = ax.imshow(np.zeros((7, 24)), aspect=asp, cmap='Greens', vmin=0, vmax=1,
                                         interpolation='nearest')
                ax.set_title("ОБЩИЙ ПЛАН (СОВПАДЕНИЯ)", color=self.TEXT_DIM, fontweight='bold', fontsize=9, pad=10)

            ax.set_box_aspect(7 / 24)
            ax.set_xticks(range(24))
            ax.set_yticks(range(7))
            ax.set_yticklabels(['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'], fontsize=7, color=self.ACCENT_BLUE,
                               fontweight='bold')
            ax.tick_params(colors=self.TEXT_DIM, labelsize=6, length=0, pad=2)
            ax.set_xticks(np.arange(-.5, 24, 1), minor=True)
            ax.set_yticks(np.arange(-.5, 7, 1), minor=True)
            ax.grid(which="minor", color=self.REF_LINES, linestyle='-', linewidth=0.5)
            for spine in ax.spines.values(): spine.set_edgecolor(self.REF_LINES)

        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        container.winfo_toplevel().bind("<KeyPress>", self.on_key_tk)

        self.update_view()

    def update_data_from_server(self, nick, new_grid_list):
        for s in self.schedules:
            if str(s['nick']).lower() == str(nick).lower():
                s['grid'] = np.array(new_grid_list)
                self.update_view()
                break

    def on_scroll(self, event):
        if event.button == 'up':
            self.scroll_up()
        elif event.button == 'down':
            self.scroll_down()

    def scroll_up(self):
        self.current_scroll = max(0, self.current_scroll - 1)
        self.update_view()

    def scroll_down(self):
        self.current_scroll = min(max(0, self.num_people - self.visible_count), self.current_scroll + 1)
        self.update_view()

    def update_view(self):
        for i in range(self.visible_count):
            idx = self.current_scroll + i
            ax = self.axes[i]
            if idx < self.num_people:
                s = self.schedules[idx]
                self.imgs[i].set_data(s['grid'])
                is_me = str(s['nick']).lower() == self.my_nick
                name = f" {str(s['nick']).upper()} " + ("(ВЫ)" if is_me else "")
                text_col = "white" if is_me else ("black" if self.REF_BG == "#F0F0F0" else "white")
                bg_col = self.ACCENT_BLUE if is_me else self.REF_HEADER
                ax.set_title(name, color=text_col, fontsize=8, fontweight='bold', loc='left', backgroundcolor=bg_col)
                ax.set_visible(True)
            else:
                ax.set_visible(False)
        self.res_img.set_data(self.get_common_gradient())
        self.canvas.draw()

    def get_common_gradient(self):
        if not self.schedules or self.num_people == 0: return np.zeros((7, 24))
        total_free = np.zeros((7, 24))
        for s in self.schedules: total_free += s['grid']
        return total_free / max(1, self.num_people)

    def find_my_schedule_idx(self):
        for i, s in enumerate(self.schedules):
            if str(s['nick']).lower() == self.my_nick: return i
        return None

    def find_hovered_schedule_idx(self):
        if self.mouse_pos and self.last_hovered_axis:
            for i in range(self.visible_count):
                if self.last_hovered_axis == self.axes[i]:
                    return self.current_scroll + i
        return None

    def _trigger_update(self, nick, grid):
        if self.on_grid_update:
            self.on_grid_update(nick, grid.tolist())

    def on_motion(self, event):
        if event.inaxes is not None:
            self.last_hovered_axis = event.inaxes
            self.mouse_pos = (int(event.xdata + 0.5), int(event.ydata + 0.5))
        else:
            self.last_hovered_axis = None

    def action_reset(self):
        idx = self.find_my_schedule_idx()
        if idx is not None:
            self.schedules[idx]['grid'] = np.zeros((7, 24))
            self._trigger_update(self.schedules[idx]['nick'], self.schedules[idx]['grid'])
            self.update_view()

    def action_fill_week(self):
        idx = self.find_my_schedule_idx()
        if idx is not None:
            self.schedules[idx]['grid'] = np.ones((7, 24))
            self._trigger_update(self.schedules[idx]['nick'], self.schedules[idx]['grid'])
            self.update_view()

    def action_fill_day(self):
        if not self.mouse_pos: return
        idx = self.find_hovered_schedule_idx()
        if idx is None or str(self.schedules[idx]['nick']).lower() != self.my_nick:
            idx = self.find_my_schedule_idx()

        if idx is not None:
            _, d = self.mouse_pos
            if 0 <= d < 7:
                grid = self.schedules[idx]['grid']
                grid[d, :] = 1.0 - grid[d, :]
                self._trigger_update(self.schedules[idx]['nick'], grid)
                self.update_view()

    def action_save_matches(self):
        try:
            desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
            if not os.path.exists(desktop): desktop = os.getcwd()
            filename = os.path.join(desktop, f"Расписание_{self.my_nick}_{int(time.time())}.png")
            self.fig.savefig(filename, facecolor=self.fig.get_facecolor(), bbox_inches='tight')
            messagebox.showinfo("Сохранено", f"Расписание успешно сохранено на рабочий стол:\n{filename}")
        except Exception:
            self.fig.savefig("Schedule_Match.png")
            messagebox.showinfo("Сохранено", "Расписание сохранено в папку с программой (Schedule_Match.png)")

    def on_key_tk(self, event):
        key = event.keysym.lower()
        if key == 'up':
            self.scroll_up()
        elif key == 'down':
            self.scroll_down()
        elif key in ['s', 'ы', 'save']:
            self.action_save_matches()

        idx = self.find_hovered_schedule_idx()
        if idx is None or str(self.schedules[idx]['nick']).lower() != self.my_nick:
            idx = self.find_my_schedule_idx()

        if idx is not None:
            grid = self.schedules[idx]['grid']
            changed = False
            if key in ['r', 'к', 'reset']:
                grid[:] = 0.0;
                changed = True
            elif key in ['f', 'а', 'fill']:
                grid[:] = 1.0;
                changed = True
            elif key in ['d', 'в', 'day'] and self.mouse_pos:
                _, d = self.mouse_pos
                if 0 <= d < 7:
                    grid[d, :] = 1.0 - grid[d, :]
                    changed = True
            if changed:
                self._trigger_update(self.schedules[idx]['nick'], grid)
                self.update_view()

    def on_press(self, event):
        if event.inaxes is None: return
        for i in range(self.visible_count):
            if event.inaxes == self.axes[i]:
                idx = self.current_scroll + i
                if idx >= len(self.schedules): continue

                if str(self.schedules[idx]['nick']).lower() != self.my_nick:
                    return

                h, d = int(event.xdata + 0.5), int(event.ydata + 0.5)
                if 0 <= d < 7 and 0 <= h < 24:
                    new_val = 1.0 if self.schedules[idx]['grid'][d, h] == 0 else 0.0
                    self.schedules[idx]['grid'][d, h] = new_val
                    self._trigger_update(self.schedules[idx]['nick'], self.schedules[idx]['grid'])
                    self.update_view()