#!/usr/bin/env python
# -*-    Mode: Python; coding: utf-8; indent-tabs-mode: nil; tab-width: 4    -*-

'''
TODO:
    - add scan baudrate in 'unit_supported'
    - add scan supported unit (LOAD_DC_NAME -> [])
    - do period in poll_device
'''

import os
import ntpath
import time
import datetime
import struct
import sys
import glob
import configparser
import re
import queue
from threading import Thread, Lock

import serial
import serial.tools.list_ports as port_list

import tkinter as tk
from tkinter import ttk, StringVar, font

import matplotlib.pyplot as plt
from matplotlib.backend_bases import key_press_handler
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                               NavigationToolbar2Tk)
from matplotlib.figure import Figure
import numpy as np

LOAD_DC_NAME = "ET5406A+"
FILE_INI = 'Battery_Discharge.ini'

DEF_CURRENT_DISCHARGE = 0.1         # Ampers
DEF_VOLTAGE_END_DISCHARGE = 1.0     # Voltage
DEF_CURRENT_STOP_DISCHARGE = 0.010  # Ampers

LiIon_CURRENT_DISCHARGE = 0.1         # Ampers
LiIon_VOLTAGE_END_DISCHARGE = 2.7     # Voltage
LiIon_CURRENT_STOP_DISCHARGE = 0.010  # Ampers

NiMH_CURRENT_DISCHARGE = 0.1         # Ampers
NiMH_VOLTAGE_END_DISCHARGE = 1.0     # Voltage
NiMH_CURRENT_STOP_DISCHARGE = 0.010  # Ampers

PbLead_CURRENT_DISCHARGE = 0.1         # Ampers
PbLead_VOLTAGE_END_DISCHARGE = 1.8     # Voltage
PbLead_CURRENT_STOP_DISCHARGE = 0.010  # Ampers

def dict_ser_ports():
        if sys.platform.startswith('win'):
            ports = [p.name for p in port_list.comports()]
        elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
            ports = glob.glob('/dev/tty[A-Za-z]*')
        else:
            raise EnvironmentError('Unsupported platform')
        return {ntpath.basename(port): port for port in ports}


def main():
    '''
        Main function called at start
    '''

    def enable_form(parent):
        for child in parent.winfo_children():
            wtype = child.winfo_class()
            if wtype not in ('Frame', 'Labelframe'):
                if wtype not in ('TCombobox'):
                    child.configure(state='normal')
                else:
                    child['state'] = 'readonly'
            else:
                enable_form(child)

    def disable_form(parent):
        for child in parent.winfo_children():
            wtype = child.winfo_class()
            if wtype not in ('Frame', 'Labelframe'):
                child.configure(state='disabled')
            else:
                disable_form(child)


    def scpi_send_cmd(port, cmd):
        port.write(str.encode(cmd) + b'\x0A')
        return port.read_until(expected=b'\r\n') == b'Rexecu success\r\n'

    def scpi_req_val(port, cmd):
        port.write(str.encode(cmd) + b'\x0A')
        numeric_const_pattern = r"""
        [-+]? # optional sign
        (?:
            (?: \d* \. \d+ ) # .1 .12 .123 etc 9.1 etc 98.1 etc
            |
            (?: \d+ \.? ) # 1. 12. 123. etc 1 12 123 etc
        )
        # followed by optional exponent part if desired
        (?: [Ee] [+-]? \d+ ) ?
        """
        rx = re.compile(numeric_const_pattern, re.VERBOSE)
        return [float(n) for n in rx.findall(port.read_until(expected=b'\r\n').decode('utf-8'))]

    def scpi_req_str(port, cmd):
        port.write(str.encode(cmd) + b'\x0A')
        answer = port.read_until(expected=b'\r\n').decode('utf-8')[:-2]
        #print(answer)
        return answer


    def dev_supported(port):
        result = {}
        dev = serial.Serial()
        dev.port = port
        dev.baudrate = 115200
        dev.bytesize = serial.EIGHTBITS
        dev.parity = serial.PARITY_NONE
        dev.rtscts = False
        dev.dsrdtr = False
        dev.timeout = 2
        dev.write_timeout = None
        try:
            dev.open()
        except Exception as e:
            print('Error open serial port {}: {}'.format(dev.name, e))
        else:
            if scpi_req_str(dev, "*IDN?").find(LOAD_DC_NAME) == -1:
                print("DC Load type not supported")
            else:
                a = scpi_req_str(dev, "*IDN?")
                scpi_send_cmd(dev, "SYST:LOCA")
                al = a.rstrip("\r").replace(",", " ").split(" ")
                result = {'port': port, 'name': al[0], 'sn': al[1]}
            dev.close()
        return result


    def poll_device(id=None, param=None, period=1.0, queue=None):
        if id['port'] == None or queue == None:
            return
        dev = serial.Serial()
        dev.port = id['port']
        dev.baudrate = 115200
        dev.bytesize = serial.EIGHTBITS
        dev.parity = serial.PARITY_NONE
        dev.rtscts = False
        dev.dsrdtr = False
        dev.timeout = 2
        dev.write_timeout = None
        try:
            dev.open()
        except Exception as e:
            print('Error open serial port {}: {}'.format(dev.name, e))
        else:
            mode = 'cc'
            init = True
            while proc_run:
                if init:
                    if mode == 'cc':
                        print("Fixed current mode discharge")
                        scpi_send_cmd(dev, "CH:MODE CC")
                        scpi_send_cmd(dev, f"CURR:CC {param['ccm_discharge']:.3f}")
                    elif mode == 'cv':
                        print("Fixed voltage mode discharge")
                        scpi_send_cmd(dev, "CH:MODE CV")
                        scpi_send_cmd(dev, f"VOLT:CV {param['ccm_end_voltage']:.3f}")
                    init = False
                    time.sleep(1 - time.time() % 1)
                    scpi_send_cmd(dev, "CH:SW ON")
                    buff = [scpi_req_val(dev, "MEAS:ALL?")[:2] + [time.time()], None]
                    if mode == 'cc':
                        start_t = buff[0][2]
                queue.put({'time': buff[0][2], 'i': buff[0][0], 'v': buff[0][1], 'mode': mode, 'start': start_t})
                buff[1] = buff[0]
                time.sleep(1 - time.time() % 1)
                buff[0] = scpi_req_val(dev, "MEAS:ALL?")[:2] + [time.time()]
                if mode == 'cc' and buff[0][1] < param['ccm_end_voltage']:
                    mode = 'cv'
                    init = True
                elif mode == 'cv' and buff[0][0] < param['cvm_stop_current']:
                    break
            scpi_send_cmd(dev, "CH:SW OFF")
            scpi_send_cmd(dev, "SYST:BEEP")
            scpi_send_cmd(dev, "SYST:LOCA")
            dev.close()


    def start_stop():
        nonlocal proc_run, proc_poll, sample
        if (btn_ss['text'] == "Start"):
            enable_form(frm_params)
            proc_run = True
            proc_poll = Thread(target=poll_device, args=(id, battery_param, 1.0, sample))
            proc_poll.start()
            btn_ss['text'] = "Stop"
        else:
            proc_run = False
            proc_poll.join()
            btn_ss['text'] = "Start"
            disable_form(frm_params)


    def update_measure():
        if sample == None or sample.empty():
            if not proc_run:
                pass
                #lbl_res['text'] = "inf"
            root.after(100, update_measure)
            return
        data = sample.get(block=False)
        lbl_volt['text'] = str(data['v'])
        lbl_curr['text'] = str(data['i'])
        lbl_time['text'] = str(datetime.timedelta(seconds = round(data['time'] - data['start'])))
        lbl_mode['text'] = str(data['mode']).upper()
        root.after(100, update_measure)


    def set_param_battery(battery_type):
        if battery_type == 'Ni-MH':
            battery_param = {'ccm_discharge': NiMH_CURRENT_DISCHARGE,
                             'ccm_end_voltage': NiMH_VOLTAGE_END_DISCHARGE,
                             'cvm_stop_current': NiMH_CURRENT_STOP_DISCHARGE}
        elif battery_type == 'Li-Ion':
            battery_param = {'ccm_discharge': LiIon_CURRENT_DISCHARGE,
                             'ccm_end_voltage': LiIon_VOLTAGE_END_DISCHARGE,
                             'cvm_stop_current': LiIon_CURRENT_STOP_DISCHARGE}
        elif battery_type == 'Pb-Lead':
            battery_param = {'ccm_discharge': PbLead_CURRENT_DISCHARGE,
                             'ccm_end_voltage': PbLead_VOLTAGE_END_DISCHARGE,
                             'cvm_stop_current': PbLead_CURRENT_STOP_DISCHARGE}
        text_ccm_cd.set(str(battery_param['ccm_discharge']))
        text_ccm_ved.set(str(battery_param['ccm_end_voltage']))
        text_cvm_csd.set(str(battery_param['cvm_stop_current']))
        return


    def on_exit():
        # Save program config
        size_pos_xy = root.geometry().replace("x", "+").split("+")
        if not main_cfg.has_section('Main_Win'):
            main_cfg.add_section('Main_Win')
        main_cfg.set('Main_Win', 'size_x', size_pos_xy[0])
        main_cfg.set('Main_Win', 'size_y', size_pos_xy[1])
        main_cfg.set('Main_Win', 'position_x', size_pos_xy[2])
        main_cfg.set('Main_Win', 'position_y', size_pos_xy[3])

        if not main_cfg.has_option('Device', 'sn'):
            main_cfg.add_section('Device')
        main_cfg.set('Device', 'sn', member_dev_sn)

        if not main_cfg.has_section('Battery'):
            main_cfg.add_section('Battery')
        main_cfg.set('Battery', 'ccm_discharge', str(battery_param['ccm_discharge']))
        main_cfg.set('Battery', 'ccm_end_voltage', str(battery_param['ccm_end_voltage']))
        main_cfg.set('Battery', 'cvm_stop_current', str(battery_param['cvm_stop_current']))

        try:
            with open(FILE_INI, 'w') as file_cfg:
                main_cfg.write(file_cfg)
                file_cfg.close()
        except:
            print("Error write config file")

        unit = serial.Serial()
        unit.port = id['port']
        unit.baudrate = 115200
        unit.bytesize = serial.EIGHTBITS
        unit.parity = serial.PARITY_NONE
        unit.rtscts = False
        unit.dsrdtr = False
        unit.timeout = 2
        unit.write_timeout = None
        try:
            unit.open()
        except Exception as e:
            print('Error open serial port {}: {}'.format(unit.name, e))
        else:
            scpi_send_cmd(unit, "CH:SW OFF")
            scpi_send_cmd(unit, "SYST:LOCA")
            unit.close()

        root.destroy()


    # -----------------------------------------------------------------
    # Init global variable
    port = None
    battery = {'v': None, 'i': None, 'time': None, 'mode': None, 'qcc': None, 'qcv': None, 'q': None}
    data_discharge = []
    proc_run = False
    proc_poll = None
    sample = queue.Queue()

    # restore program config
    main_cfg = configparser.ConfigParser()
    try:
        main_cfg.read(FILE_INI)
    except Exception as f:
        print("Error read config file. Set default config parameter", f)

    if main_cfg.has_option('Main_Win', 'size_x'):
        size_x = main_cfg['Main_Win']['size_x']
    else:
        size_x = '0'
    if main_cfg.has_option('Main_Win', 'size_y'):
        size_y = main_cfg['Main_Win']['size_y']
    else:
        size_y = '0'
    if main_cfg.has_option('Main_Win', 'position_x'):
        pos_x = main_cfg['Main_Win']['position_x']
    else:
        pos_x = '0'
    if main_cfg.has_option('Main_Win', 'position_y'):
        pos_y = main_cfg['Main_Win']['position_y']
    else:
        pos_y = '0'

    if main_cfg.has_option('Device', 'sn'):
        member_dev_sn = main_cfg['Device']['sn']
    else:
        member_dev_sn = ""

    battery_param = {}
    if main_cfg.has_option('Battery', 'ccm_discharge'):
        battery_param['ccm_discharge'] = float(main_cfg['Battery']['ccm_discharge'])
    else:
        battery_param['ccm_discharge'] = DEF_CURRENT_DISCHARGE
    if main_cfg.has_option('Battery', 'ccm_end_voltage'):
        battery_param['ccm_end_voltage'] = float(main_cfg['Battery']['ccm_end_voltage'])
    else:
        battery_param['ccm_end_voltage'] = DEF_VOLTAGE_END_DISCHARGE
    if main_cfg.has_option('Battery', 'cvm_stop_current'):
        battery_param['cvm_stop_current'] = float(main_cfg['Battery']['cvm_stop_current'])
    else:
        battery_param['cvm_stop_current'] = DEF_CURRENT_STOP_DISCHARGE


    # Create main window
    root = tk.Tk()
    root.protocol("WM_DELETE_WINDOW", on_exit)
    font_def = font.nametofont("TkDefaultFont")
    font_def.configure(family="Liberation Mono", size=10)
    root.option_add("*Font", font_def)
    root.title("Battery Discharge")

    # -----------------------------------------------------
    lbl_status = tk.Label(root, text="No DC electronic load", anchor='w', borderwidth=2, relief='sunken')
    lbl_status.pack(side='bottom', fill='x', padx=5, pady=5)


    # ----------------------------------------------------
    # Settings frame
    sys_pady = 2
    padding = {'padx': 5, 'pady': 5} # **padding

    frm_set = tk.LabelFrame(root, text=' Settings ', borderwidth=3, relief='groove')
    frm_set.pack(side='bottom', fill='x', padx=5, pady=5)

    frm_presets = tk.Frame(frm_set, borderwidth=3, relief='flat')
    frm_presets.pack(side='left', fill='y', padx=0, pady=0)

    btn_NiMH = tk.Button(frm_presets, text="Ni-MH", width=12, command=lambda: set_param_battery('Ni-MH'))
    btn_NiMH.pack(side='top', fill='y', padx=5, pady=sys_pady)

    btn_LiIon = tk.Button(frm_presets, text="Li-Ion", width=12, command=lambda: set_param_battery('Li-Ion'))
    btn_LiIon.pack(side='top', fill='y', padx=5, pady=sys_pady)

    btn_PbLead = tk.Button(frm_presets, text="Pb-Lead", width=12, command=lambda: set_param_battery('Pb-Lead'))
    btn_PbLead.pack(side='top', fill='y', padx=5, pady=sys_pady)

    frm_prop_label = tk.Frame(frm_set, borderwidth=3, relief='flat')
    frm_prop_label.pack(side='left', fill='y', expand=False, padx=0, pady=0)

    lbl_ccm_cd = tk.Label(frm_prop_label, text="CC mode current discharge")
    lbl_ccm_cd.pack(side='top', fill='y', expand=True, padx=5, pady=sys_pady, anchor='w')

    lbl_ccm_ved = tk.Label(frm_prop_label, text="CC mode voltage end discharge")
    lbl_ccm_ved.pack(side='top', fill='y', expand=True, padx=5, pady=sys_pady, anchor='w')

    lbl_cvm_csd = tk.Label(frm_prop_label, text="CV mode current stop discharge")
    lbl_cvm_csd.pack(side='top', fill='y', expand=True, padx=5, pady=sys_pady, anchor='w')

    frm_prop_entry = tk.Frame(frm_set, borderwidth=3, relief='flat')
    frm_prop_entry.pack(side='left', fill='y', expand=False, padx=0, pady=0)

    text_ccm_cd = tk.StringVar(value=str(battery_param['ccm_discharge']))
    ent_ccm_cd = ttk.Entry(frm_prop_entry, textvariable=text_ccm_cd)
    ent_ccm_cd.pack(side='top', fill='y', expand=True, padx=5, pady=sys_pady)

    text_ccm_ved = tk.StringVar(value=str(battery_param['ccm_end_voltage']))
    ent_ccm_ved = ttk.Entry(frm_prop_entry, textvariable=text_ccm_ved)
    ent_ccm_ved.pack(side='top', fill='y', expand=True, padx=5, pady=sys_pady)

    text_cvm_csd = tk.StringVar(value=str(battery_param['cvm_stop_current']))
    ent_cvm_csd = ttk.Entry(frm_prop_entry, textvariable=text_cvm_csd)
    ent_cvm_csd.pack(side='top', fill='y', expand=True, padx=5, pady=sys_pady)

    frm_prop_btn = tk.Frame(frm_set, borderwidth=3, relief='flat')
    frm_prop_btn.pack(side='left', fill='both', expand='true', padx=0, pady=0)

    btn_ss = tk.Button(frm_prop_btn, text="Start", width=12, command=start_stop)
    btn_ss.pack(side='left', fill='y', padx=5, pady=sys_pady)

    btn_exit = tk.Button(frm_prop_btn, text="Exit", width=12, command=on_exit)
    btn_exit.pack(side='right', fill='y', padx=5, pady=sys_pady)


    # ----------------------------------------------------
    # Parameters frame
    pk4_pady = 10

    frm_params = tk.LabelFrame(root, text=' Parameters ', borderwidth=3, relief='groove')
    frm_params.pack(side='bottom', fill='x', padx=5, pady=5)

    lbl_charge = tk.Label(frm_params, text="Absorbed charge: 0")
    lbl_charge.pack(side='left', padx=5, pady=pk4_pady, fill='x', expand=True)

    lbl_volt = tk.Label(frm_params, text="V: 0")
    lbl_volt.pack(side='left', padx=5, pady=pk4_pady, fill='x', expand=True)

    lbl_curr = tk.Label(frm_params, text="I: 0")
    lbl_curr.pack(side='left', padx=5, pady=pk4_pady, fill='x', expand=True)

    lbl_time = tk.Label(frm_params, text="Time: 0")
    lbl_time.pack(side='left', padx=5, pady=pk4_pady, fill='x', expand=True)

    lbl_mode = tk.Label(frm_params, text="Mode: Undefined")
    lbl_mode.pack(side='left', padx=5, pady=pk4_pady, fill='x', expand=True)

    for child in frm_params.winfo_children():
        child.config(font=('Liberation Mono', 18))


    # ----------------------------------------------------
    # Plot frame

    t = np.arange(0, 6, .01)
    s = np.sin(2*np.pi*t)

    fig = Figure(figsize=(2, 4), dpi=100)
    fig.subplots_adjust(left=0.05, right=0.975, top=0.95, bottom=0.12)
    ax = fig.add_subplot()
    line, = ax.plot(t, s, color='black')
    ax.set_xlabel("time [s]")
    ax.set_ylabel("f(t)")
    ax.axhline(0, color='black')
    ax.fill_between(t, 1, where=s > 0, facecolor='green', alpha=.5)
    ax.fill_between(t, -1, where=s < 0, facecolor='red', alpha=.5)

    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.draw()

    # pack_toolbar=False will make it easier to use a layout manager later on.
    toolbar = NavigationToolbar2Tk(canvas, root, pack_toolbar=False)
    toolbar.update()

    #canvas.mpl_connect("key_press_event", lambda event: print(f"you pressed {event.key}"))
    #canvas.mpl_connect("key_press_event", key_press_handler)

    toolbar.pack(side='bottom', fill='x')
    canvas.get_tk_widget().pack(side='top', fill='both', expand=True)


    # ------------------------------------------------------
    root.update()
    screen_width = root.winfo_screenwidth()
    #screen_height = root.winfo_screenheight()
    root.geometry(str(screen_width) + "x" + str(root.winfo_height()) + "+0+0")
    root.resizable(width='false', height='true')
    root.minsize(root.winfo_width(), root.winfo_height())

    dict_ports = dict_ser_ports()
    list_ports = list(dict_ports.values())
    list_id = []
    id = None
    for u in list(dict_ports.values()):
        d = dev_supported(u)
        if d != {}:
            list_id.append(d)
    print(list_id)
    if len(list_id) == 1:
        id = list_id[0]
        lbl_status['text'] = id['port'].split("/")[-1] + " " + id['name'] + " " + id['sn']
        member_dev_sn = ""
    else:
        if member_dev_sn != None and member_dev_sn in id.values():
            pass #port = найти порт по серийному номеру
        else:
            pass #открыть окно выбора устройства

    if id == None:
        btn_ss['state'] = 'disabled'
        disable_form(frm_params)


    update_measure()
    root.mainloop()


if __name__ == '__main__':
    main()
