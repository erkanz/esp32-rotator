"""SDR# / SDR++ signal-peaking UI integrated with the existing BLE client.

No second BLE connection: this panel shares the authenticated physical ROTOR
session and GATT lock. SDR# requires the companion VisualSNR plugin in SDR#.
"""
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Source checkout: find the existing SDR scanner library next to windows_app.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdr_scan"))

from rotator_scan import (
    SDRSharpUDPSource, IQTcpSource, angles, circular_distance, perform_scan,
    SERVICE, CMD, STATUS, REPLY,
)

LOG = logging.getLogger("rotatorble.sdr")
SDRSHARP = "SDR# (VisualSNR UDP)"
SDRPP = "SDR++ (IQ TCP)"
SDRPP_UDP = "SDR++ (SNR Plugin UDP)"


def parse_sweep(start, end, step, settle, dwell, timeout, threshold, port,
                sample_rate, bandwidth):
    azs = angles(int(start), int(end), int(step))
    settle, dwell, timeout, threshold = float(settle), float(dwell), float(timeout), float(threshold)
    port, sample_rate, bandwidth = int(port), int(sample_rate), int(bandwidth)
    if not (0 <= settle <= 30 and .4 <= dwell <= 120 and 1 <= timeout <= 300):
        raise ValueError("Settle 0–30s, dwell 0.4–120s, move timeout 1–300s")
    if not (-60 <= threshold <= 100) or not (1024 <= port <= 65535):
        raise ValueError("SNR threshold -60..100 dB and TCP/UDP port 1024..65535 required")
    if sample_rate < 24000 or sample_rate > 5000000 or bandwidth < 100 or bandwidth >= .45 * sample_rate:
        raise ValueError("SDR++ IQ sample rate / channel bandwidth is invalid")
    return azs, settle, dwell, timeout, threshold, port, sample_rate, bandwidth


class SharedRotor:
    """Use App's single authenticated BLE session; never reconnect the radio."""
    def __init__(self, app):
        self.app = app
        self.client = app.client

    async def start(self):
        if not self.app.paired or not self.client or not self.client.is_connected:
            raise RuntimeError("Connect ROTATOR-BLE using the Control tab first")
        await self.status()

    async def status(self):
        if self.client is not self.app.client or not self.app.paired or not self.client.is_connected:
            raise RuntimeError("Authenticated ROTOR BLE session lost")
        async with self.app.gatt_lock:
            data = await self.client.read_gatt_char(STATUS)
        obj = json.loads(data.decode())
        if str(obj.get("role","")).upper() not in ("ROTOR", "ROTATOR"):
            raise RuntimeError("SDR sweep requires direct ROTATOR-BLE; REMOTE is not permitted")
        if obj.get("fault"):
            raise RuntimeError("ROTOR fault %s — clear fault before scan" % obj["fault"])
        if obj.get("online") is False:
            raise RuntimeError("ROTOR is offline")
        return obj

    async def command(self, text):
        if not (text == "STOP" or text == "STATUS" or text.startswith("AZ ")):
            raise ValueError("SDR sweep only permits STOP, STATUS and AZ")
        if self.client is not self.app.client or not self.app.paired or not self.client.is_connected:
            raise RuntimeError("Authenticated ROTOR BLE session lost")
        async with self.app.gatt_lock:
            await self.client.write_gatt_char(CMD, text.encode("ascii"), response=True)
            reply = (await self.client.read_gatt_char(REPLY)).decode(errors="replace").strip()
        self.app.logger.info("SDR GATT %s -> %s", text, reply)
        if not reply.upper().startswith("OK"):
            raise RuntimeError("ROTOR rejected %s: %s" % (text, reply))
        return reply

    async def move_to(self, az, timeout, tolerance=2.0):
        before = await self.status()
        if circular_distance(float(before["az"]), az) > tolerance:
            await self.command("AZ %d" % az)
        deadline = time.monotonic() + timeout
        steady = 0
        while time.monotonic() < deadline:
            if getattr(self.app.sdr, "cancel_requested", False):
                raise asyncio.CancelledError()
            current = await self.status()
            if circular_distance(float(current["az"]), az) <= tolerance and not current.get("moving"):
                steady += 1
                if steady >= 2:
                    return
            else:
                steady = 0
            await asyncio.sleep(.3)
        raise TimeoutError("AZ %d did not settle; STOP issued" % az)

    async def stop(self):
        if self.client is self.app.client and self.app.paired and self.client and self.client.is_connected:
            try:
                await self.command("STOP")
            except Exception as exc:
                self.app.logger.error("Emergency SDR STOP failed: %s", exc)

    async def close(self):
        # BLE belongs to the Control tab. Never disconnect it after a scan.
        pass


class PassiveSource:
    """Scanner borrows the already connected SDR data source."""
    def __init__(self, source):
        self.source = source

    @property
    def latest(self):
        return self.source.latest

    @property
    def error(self):
        return self.source.error

    async def start(self):
        if self.source.error:
            raise RuntimeError("SDR connection failed: %s" % self.source.error)

    async def close(self):
        # Allow live SNR display after a completed or aborted scan.
        pass


class SDRPanel:
    def __init__(self, app, tabs):
        self.app = app
        self.root = app.root
        self.source = None
        self.connected_mode = None
        self.connecting = False
        self.scan_task = None
        self.cancel_requested = False
        self.active = False
        self.frame = ttk.Frame(tabs, padding=12)
        tabs.add(self.frame, text="SDR# / SNR Scan")

        ttk.Label(self.frame, text="SDR signal / automatic antenna peaking",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(self.frame,
                  text="Connect ROTATOR-BLE in Control first. SDR# requires the VisualSNR bridge plugin.",
                  wraplength=580).pack(anchor="w", pady=(0,8))
        conn = ttk.LabelFrame(self.frame, text="SDR connection", padding=8)
        conn.pack(fill="x")
        line = ttk.Frame(conn);line.pack(fill="x")
        ttk.Label(line,text="Source").pack(side="left")
        self.mode = tk.StringVar(value=SDRSHARP)
        self.mode_box = ttk.Combobox(line, state="readonly", textvariable=self.mode,
                                    values=(SDRSHARP,SDRPP_UDP,SDRPP), width=27)
        self.mode_box.pack(side="left",padx=6)
        self.mode_box.bind("<<ComboboxSelected>>",self._mode_changed)
        ttk.Label(line,text="Port").pack(side="left")
        self.port = tk.StringVar(value="47291")
        ttk.Entry(line, textvariable=self.port, width=7).pack(side="left",padx=5)
        ttk.Button(line,text="Connect SDR",command=self.connect).pack(side="left",padx=2)
        ttk.Button(line,text="Disconnect",command=self.disconnect).pack(side="left",padx=2)
        self.live = tk.StringVar(value="SDR disconnected")
        ttk.Label(conn,textvariable=self.live,wraplength=600).pack(anchor="w",pady=5)
        self.rate = tk.StringVar(value="96000")
        self.bandwidth = tk.StringVar(value="12500")
        advanced=ttk.Frame(conn);advanced.pack(fill="x")
        ttk.Label(advanced,text="SDR++ IQ rate (Hz)").pack(side="left")
        ttk.Entry(advanced,textvariable=self.rate,width=9).pack(side="left",padx=4)
        ttk.Label(advanced,text="Channel BW (Hz)").pack(side="left")
        ttk.Entry(advanced,textvariable=self.bandwidth,width=9).pack(side="left",padx=4)

        cfg=ttk.LabelFrame(self.frame,text="Automatic azimuth scan",padding=8)
        cfg.pack(fill="x",pady=8)
        self.start = tk.StringVar(value="90")
        self.end = tk.StringVar(value="180")
        self.step = tk.StringVar(value="10")
        self.settle = tk.StringVar(value="1.5")
        self.dwell = tk.StringVar(value="3.0")
        self.timeout = tk.StringVar(value="45")
        self.min_db = tk.StringVar(value="1.0")
        first=ttk.Frame(cfg);first.pack(fill="x")
        for label,v,w in (("From °",self.start,5),("To °",self.end,5),
                          ("Step °",self.step,5),("Settle s",self.settle,6)):
            ttk.Label(first,text=label).pack(side="left")
            ttk.Entry(first,textvariable=v,width=w).pack(side="left",padx=(3,9))
        second=ttk.Frame(cfg);second.pack(fill="x",pady=5)
        for label,v,w in (("Measure s",self.dwell,6),("Move timeout s",self.timeout,6),
                          ("Min SNR dB",self.min_db,6)):
            ttk.Label(second,text=label).pack(side="left")
            ttk.Entry(second,textvariable=v,width=w).pack(side="left",padx=(3,9))

        dest=ttk.Frame(cfg);dest.pack(fill="x",pady=3)
        ttk.Label(dest,text="CSV").pack(side="left")
        folder=Path.home()/"Documents"/"Rotator"
        self.csv=tk.StringVar(value=str(folder/("snr_scan_"+datetime.now().strftime("%Y%m%d_%H%M")+".csv")))
        ttk.Entry(dest,textvariable=self.csv).pack(side="left",fill="x",expand=True,padx=4)
        ttk.Button(dest,text="Browse",command=self.browse).pack(side="left")

        actions=ttk.Frame(self.frame);actions.pack(fill="x",pady=4)
        ttk.Button(actions,text="START SNR SCAN",command=self.start_scan).pack(side="left",padx=4)
        ttk.Button(actions,text="STOP SCAN / STOP MOTOR",command=self.cancel).pack(side="left",padx=4)
        self.info=tk.StringVar(value="Ready: first connect SDR# and physical ROTATOR-BLE")
        ttk.Label(self.frame,textvariable=self.info,wraplength=610).pack(anchor="w",pady=4)

        result=ttk.LabelFrame(self.frame,text="SNR by direction (relative dB)",padding=4)
        result.pack(fill="both",expand=True,pady=4)
        self.table=ttk.Treeview(result,columns=("az","snr","spread","count","freq"),show="headings",height=8)
        for name,label,width in (("az","AZ (°)",64),("snr","SNR (dB)",100),
                                 ("spread","Spread (dB)",96),("count","Samples",74),("freq","Frequency (Hz)",145)):
            self.table.heading(name,text=label)
            self.table.column(name,width=width,anchor="center",stretch=name=="freq")
        self.table.pack(fill="both",expand=True)
        self.root.after(300,self._refresh)

    def _mode_changed(self,_evt=None):
        if self.source is not None:
            self.mode.set(self.connected_mode)
            messagebox.showinfo("SDR", "Disconnect the SDR before changing source")
            return
        self.port.set("1234" if self.mode.get()==SDRPP else "47291")

    def browse(self):
        selected=filedialog.asksaveasfilename(title="SNR CSV file",defaultextension=".csv",
            filetypes=[("CSV files","*.csv")],initialfile=Path(self.csv.get()).name)
        if selected:self.csv.set(selected)

    def connect(self):
        if self.source is not None or self.connecting or self.active:
            return
        try:
            port=int(self.port.get())
            rate=int(self.rate.get())
            bw=int(self.bandwidth.get())
            if not 1024 <= port <= 65535:raise ValueError("Port out of range")
            if self.mode.get()==SDRPP and (rate<24000 or bw<100 or bw>=rate*.45):
                raise ValueError("Invalid IQ sampling parameters")
        except ValueError as exc:
            messagebox.showerror("SDR settings",str(exc))
            return
        self.connecting=True
        mode=self.mode.get()
        self.info.set("Connecting SDR source...")
        self.app.call(self._connect(mode,port,rate,bw))

    async def _connect(self,mode,port,rate,bw):
        candidate=SDRSharpUDPSource(port) if mode in (SDRSHARP,SDRPP_UDP) else IQTcpSource("127.0.0.1",port,rate,bw)
        try:
            await candidate.start()
            self.source=candidate
            self.connected_mode=mode
            self.app.logger.info("SDR source opened: %s localhost port %d",mode,port)
            msg=("Listening for SDR# VisualSNR UDP packets. Start SDR# with the plugin."
                 if mode==SDRSHARP else
                 "Listening for SDR++ Rotator SNR plugin UDP packets."
                 if mode==SDRPP_UDP else "SDR++ IQ stream opened; checking samples...")
            self.app.ui(lambda:self.info.set(msg))
        except Exception as exc:
            self.app.logger.error("SDR connect failed: %s",exc,exc_info=True)
            try:await candidate.close()
            except Exception:pass
            self.app.ui(lambda:self.info.set("SDR connection failed: "+str(exc)))
        finally:
            self.connecting=False

    def disconnect(self):
        if self.active:
            messagebox.showwarning("SDR","Stop the scan before disconnecting SDR")
            return
        self.app.call(self._disconnect())

    async def _disconnect(self):
        src=self.source
        self.source=None
        self.connected_mode=None
        if src is not None:
            await src.close()
        self.app.ui(lambda:self.info.set("SDR disconnected"))

    def _refresh(self):
        if not self.app.running:return
        source=self.source
        if source is None:
            message="SDR disconnected" if not self.connecting else "Connecting..."
        elif source.error:
            message="SDR stream error: "+str(source.error)
        elif source.latest is None:
            message=("Waiting for live SDR# VisualSNR frames..." if self.connected_mode==SDRSHARP
                     else "Waiting for SDR++ SNR plugin UDP frames..." if self.connected_mode==SDRPP_UDP
                     else "Waiting for IQ stream...")
        else:
            sample=source.latest
            age=time.monotonic()-sample.received
            if age>2.0:message="SDR signal LOST (%.1fs since last update) — scan blocked"%age
            else:
                frequency=("%d Hz"%sample.frequency_hz) if sample.frequency_hz is not None else "frequency not reported"
                message="SDR ACTIVE | SNR %.2f dB | %s | age %.1fs"%(sample.db,frequency,age)
        self.live.set(message)
        self.root.after(300,self._refresh)

    def start_scan(self):
        if self.active or self.connecting:return
        if self.source is None or self.source.error:
            messagebox.showerror("SNR scan","Connect SDR and wait for a live SNR measurement")
            return
        if self.connected_mode != self.mode.get():
            messagebox.showerror("SNR scan","SDR source selection changed; reconnect")
            return
        sample=self.source.latest
        if sample is None or time.monotonic()-sample.received>1.5:
            messagebox.showerror("SNR scan","No fresh SDR data. Check the SDR# bridge / IQ Exporter")
            return
        if (not self.app.paired or not self.app.client or not self.app.client.is_connected or
                str((self.app.last_status or {}).get("role","")).upper() not in ("ROTOR","ROTATOR")):
            messagebox.showerror("SNR scan","Connect directly to ROTATOR-BLE in the Control tab (not REMOTE)")
            return
        if self.app.jog:
            messagebox.showerror("SNR scan","Release manual JOG before auto scan")
            return
        try:
            cfg=parse_sweep(self.start.get(),self.end.get(),self.step.get(),
                self.settle.get(),self.dwell.get(),self.timeout.get(),self.min_db.get(),
                self.port.get(),self.rate.get(),self.bandwidth.get())
            filename=Path(self.csv.get()).expanduser()
            if not str(filename) or filename.suffix.lower()!=".csv":
                raise ValueError("Select a .csv output file")
        except (ValueError,OSError) as exc:
            messagebox.showerror("Invalid scan settings",str(exc))
            return
        if not messagebox.askyesno("Confirm physical movement",
            "Move antenna across %d positions, from %d° to %d°?\nEnsure the travel path is safe."%
            (len(cfg[0]),cfg[0][0],cfg[0][-1])):
            return
        self.cancel_requested=False
        self.active=True
        self.app.scan_active=True
        for item in self.table.get_children():self.table.delete(item)
        self.info.set("Scan started — verifying ROTOR and SDR data...")
        self.app.call(self._scan(cfg,filename))

    def _progress(self,phase,az,row,i,total):
        if phase=="moving":
            self.app.ui(lambda:self.info.set("Moving to %d° (%d/%d)"%(az,i,total)))
        elif phase=="sample":
            def update():
                self.table.insert("","end",values=(row.az,"%.2f"%row.median_db,
                    "%.2f"%row.stdev_db,row.count,row.frequency_hz or "—"))
                self.info.set("AZ %d°: SNR %.2f dB (%d/%d)"%
                    (row.az,row.median_db,i,total))
            self.app.ui(update)
        elif phase=="best":
            self.app.ui(lambda:self.info.set(
                "Best: AZ %d°, SNR %.2f dB; moving to peak..."%(az,row.median_db)))

    async def _scan(self,cfg,filename):
        self.scan_task=asyncio.current_task()
        try:
            if self.cancel_requested:raise asyncio.CancelledError()
            azs,settle,dwell,timeout,threshold,*_=cfg
            rotor=SharedRotor(self.app)
            source=PassiveSource(self.source)
            best,rows=await perform_scan(
                rotor,source,azs,settle=settle,dwell=dwell,timeout=timeout,
                output=filename,min_db=threshold,progress=self._progress)
            self.app.logger.info("SDR scan completed: best AZ=%d SNR=%.2f CSV=%s",
                best.az,best.median_db,filename)
            self.app.ui(lambda:self.info.set("COMPLETE | BEST AZ %d° | %.2f dB | %s"%
                (best.az,best.median_db,filename)))
        except asyncio.CancelledError:
            self.app.logger.warning("SDR scan canceled, STOP attempted")
            self.app.ui(lambda:self.info.set("Scan canceled. STOP sent to ROTOR."))
        except Exception as exc:
            self.app.logger.error("SDR scan aborted: %s",exc,exc_info=True)
            self.app.ui(lambda:self.info.set("Scan stopped: "+str(exc)))
        finally:
            self.active=False
            self.app.scan_active=False
            self.scan_task=None

    def cancel(self):
        if self.active:
            self.cancel_requested=True
            task=self.scan_task
            if task is not None:
                self.app.loop.call_soon_threadsafe(task.cancel)
            self.info.set("Stopping scan and sending motor STOP...")
        if self.app.paired:
            self.app.call(self._stop_motor())

    async def _stop_motor(self):
        if self.app.paired and self.app.client and self.app.client.is_connected:
            async with self.app.gatt_lock:
                await self.app.client.write_gatt_char(CMD,b"STOP",response=True)
                reply=(await self.app.client.read_gatt_char(REPLY)).decode(errors="replace")
            self.app.logger.warning("SDR manual STOP -> %s",reply)

    def close(self):
        self.cancel_requested=True
        task=self.scan_task
        if task is not None:self.app.loop.call_soon_threadsafe(task.cancel)
