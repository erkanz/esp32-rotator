"""F11 Windows BLE client for both ROTATOR and REMOTE (R5.12 GATT)."""
import asyncio
from collections import deque
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from bleak import BleakClient, BleakScanner

SERVICE="df8268c0-4cc2-4eaa-85dd-3a6159fe0001"
CMD="df8268c0-4cc2-4eaa-85dd-3a6159fe0002"
STATUS="df8268c0-4cc2-4eaa-85dd-3a6159fe0003"
REPLY="df8268c0-4cc2-4eaa-85dd-3a6159fe0004"

FAIL = 45
logging.addLevelName(FAIL, "FAIL")

def classify_reply(reply):
 upper = reply.strip().upper()
 if upper.startswith(("FAIL", "NACK")):return FAIL
 if upper.startswith(("ERR", "ERROR", "DENIED", "REJECT")):return logging.ERROR
 if upper.startswith(("WARN", "BUSY")):return logging.WARNING
 return logging.INFO

class UiLogHandler(logging.Handler):
 def __init__(self, events):
  super().__init__(logging.DEBUG);self.events=events
 def emit(self, record):
  try:self.events.put(("log",record.levelno,self.format(record)))
  except Exception:self.handleError(record)

def make_logger(events):
 log=logging.getLogger("rotatorble")
 log.setLevel(logging.DEBUG);log.propagate=False
 log.handlers.clear()
 fmt=logging.Formatter("%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s","%Y-%m-%d %H:%M:%S")
 ui=UiLogHandler(events);ui.setFormatter(fmt);log.addHandler(ui)
 filename="(disk log unavailable)"
 try:
  base=Path(os.environ.get("LOCALAPPDATA") or (Path.home()/".rotatorble"))
  dest=base/"RotatorBLE"/"logs"/"rotator_ble.log"
  dest.parent.mkdir(parents=True,exist_ok=True)
  handler=RotatingFileHandler(dest,maxBytes=2*1024*1024,backupCount=3,encoding="utf-8")
  handler.setFormatter(fmt);log.addHandler(handler);filename=str(dest)
 except OSError as exc:log.warning("Disk log unavailable: %s",exc)
 bleak_logger=logging.getLogger("bleak")
 bleak_logger.setLevel(logging.WARNING)
 bleak_logger.handlers=[ui]+[h for h in log.handlers if isinstance(h,RotatingFileHandler)]
 bleak_logger.propagate=False
 return log,filename

class App:
 def __init__(self,root):
  self.root=root;root.title("Rotator BLE — REMOTE / ROTATOR");root.geometry("560x600")
  self.loop=asyncio.new_event_loop();threading.Thread(target=self._worker,daemon=True).start()
  self.devices=[];self.client=None;self.running=True;self.jog=0;self.scanning=False
  self.events=queue.Queue();self.history=deque(maxlen=4000);self.logger,self.logfile=make_logger(self.events)
  self.gatt_lock=asyncio.Lock();self.jog_token=0;self.last_status=None;self.paired=False;self.connection_generation=0;self.connecting=False
  tabs=ttk.Notebook(root);tabs.pack(fill="both",expand=True,padx=8,pady=8)
  frame=ttk.Frame(tabs,padding=16);logs=ttk.Frame(tabs,padding=8)
  tabs.add(frame,text="Control");tabs.add(logs,text="Logs")
  ttk.Label(frame,text="ROTATOR BLE / REMOTE BLE",font=("Segoe UI",16,"bold")).pack()
  self.choice=ttk.Combobox(frame,state="readonly",width=48);self.choice.pack(fill="x",pady=8)
  bar=ttk.Frame(frame);bar.pack()
  ttk.Button(bar,text="Scan",command=lambda:self.call(self.scan())).pack(side="left")
  ttk.Button(bar,text="Connect (read-only)",command=lambda:self.call(self.connect(self.choice.current()))).pack(side="left")
  ttk.Button(bar,text="Pair / Authenticate",command=lambda:self.call(self.pair_connection())).pack(side="left")
  ttk.Button(bar,text="Disconnect",command=lambda:self.call(self.disconnect())).pack(side="left")
  self.status=tk.StringVar(value="Disconnected");ttk.Label(frame,textvariable=self.status,wraplength=490).pack(pady=10)
  self.az=self.field(frame,"Target AZ 0–359","90")
  bar=ttk.Frame(frame);bar.pack(pady=4)
  for label,cmd in (("GO",self.go),("STOP",lambda:self.command("STOP")),("HOME",lambda:self.command("HOME"))):
   ttk.Button(bar,text=label,command=cmd).pack(side="left")
  bar=ttk.Frame(frame);bar.pack(pady=5)
  for label,direction in (("◀ CCW",-1),("CW ▶",1)):
   b=ttk.Button(bar,text=label);b.pack(side="left",padx=8)
   b.bind("<ButtonPress-1>",lambda e,d=direction:self.start_jog(d))
   b.bind("<ButtonRelease-1>",lambda e:self.stop_jog())
   b.bind("<Leave>",lambda e:self.stop_jog())
  for key,low,high,default in (("CURRENT",500,1800,1400),("SPEED",200,6000,2400),("ACCEL",300,4000,1800)):
   inp=self.field(frame,f"{key}: {low}–{high}",str(default))
   ttk.Button(frame,text="Set "+key,command=lambda k=key,i=inp,lo=low,hi=high:self.set_value(k,i,lo,hi)).pack()
  ttk.Button(frame,text="Clear fault",command=lambda:self.command("CLEAR")).pack()
  self.notice=tk.StringVar(value="Pair BLE device via Windows if requested. Open Logs for diagnostics.")
  ttk.Label(frame,textvariable=self.notice,wraplength=590).pack(pady=8)
  ttk.Button(frame,text="Open Logs",command=lambda:tabs.select(logs)).pack()
  self.build_log_tab(logs)
  root.bind("<FocusOut>",lambda e:self.stop_jog());root.protocol("WM_DELETE_WINDOW",self.close)
  root.report_callback_exception=self.tk_error
  root.after(120,self.drain_logs)
  self.logger.info("Windows BLE control app launched. Automatic log: %s",self.logfile)
  self.logger.info("Expected BLE service UUID: %s",SERVICE)
 def _worker(self):
  asyncio.set_event_loop(self.loop)
  self.loop.set_exception_handler(lambda loop,ctx:self.logger.error("Asyncio failure: %s",ctx.get("message"),exc_info=(type(ctx["exception"]),ctx["exception"],ctx["exception"].__traceback__) if ctx.get("exception") else None))
  self.loop.run_forever()
 def call(self,coro):
  future=asyncio.run_coroutine_threadsafe(coro,self.loop)
  def done(f):
   try:f.result()
   except Exception as e:
    self.logger.log(FAIL,"%s failed: %s: %s",getattr(coro,"__name__", "BLE operation"),type(e).__name__,e,exc_info=(type(e),e,e.__traceback__))
    self.set_log(f"Operation failed: {e}. See Logs tab.")
  future.add_done_callback(done)
 def ui(self,func):self.events.put(("ui",func))
 def set_log(self,msg):self.ui(lambda:self.notice.set(msg))
 def build_log_tab(self,tab):
  top=ttk.Frame(tab);top.pack(fill="x",pady=4)
  ttk.Label(top,text="Severity").pack(side="left")
  self.severity=tk.StringVar(value="All")
  chooser=ttk.Combobox(top,textvariable=self.severity,values=("All","Warnings+","Errors / Fail"),state="readonly",width=18)
  chooser.pack(side="left",padx=4);chooser.bind("<<ComboboxSelected>>",lambda e:self.render_logs())
  ttk.Button(top,text="Copy All",command=self.copy_logs).pack(side="left",padx=3)
  ttk.Button(top,text="Save As...",command=self.save_logs).pack(side="left",padx=3)
  ttk.Button(top,text="Clear View",command=self.clear_logs).pack(side="left",padx=3)
  self.logtext=scrolledtext.ScrolledText(tab,wrap="word",state="disabled",font=("Consolas",9))
  self.logtext.pack(fill="both",expand=True)
  self.logtext.tag_configure("warning",foreground="#916500")
  self.logtext.tag_configure("error",foreground="#bf2828")
  self.logtext.tag_configure("fail",foreground="#b30032")
  ttk.Label(tab,text="Automatic log file: "+self.logfile,wraplength=580).pack(fill="x",pady=6)
  ttk.Label(tab,text="Review BLE device identifiers before sharing logs.").pack(fill="x")
 def visible_log(self,level):
  selected=self.severity.get()
  return selected=="All" or (selected=="Warnings+" and level>=logging.WARNING) or (selected=="Errors / Fail" and level>=logging.ERROR)
 def display_line(self,level,line):
  was_at_bottom=self.logtext.yview()[1]>=0.97
  self.logtext.config(state="normal")
  tag="fail" if level>=FAIL else "error" if level>=logging.ERROR else "warning" if level>=logging.WARNING else None
  self.logtext.insert("end",line+"\n",tag)
  self.logtext.config(state="disabled")
  if was_at_bottom:self.logtext.see("end")
 def drain_logs(self):
  try:
   for _ in range(350):
    try:item=self.events.get_nowait()
    except queue.Empty:break
    if item[0]=="ui":item[1]()
    else:
     _,level,line=item;self.history.append((level,line))
     if self.visible_log(level):self.display_line(level,line)
  except Exception:self.logger.exception("Log/UI render failure")
  if self.running:self.root.after(120,self.drain_logs)
 def render_logs(self):
  self.logtext.config(state="normal");self.logtext.delete("1.0","end");self.logtext.config(state="disabled")
  for level,line in self.history:
   if self.visible_log(level):self.display_line(level,line)
 def logs_as_text(self):
  return "\n".join(line for level,line in self.history if self.visible_log(level))+"\n"
 def copy_logs(self):
  self.root.clipboard_clear();self.root.clipboard_append(self.logs_as_text())
  self.logger.info("Visible logs copied to clipboard")
 def save_logs(self):
  name="RotatorBLE-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".log"
  target=filedialog.asksaveasfilename(title="Save diagnostics",initialfile=name,defaultextension=".log",filetypes=(("Log files","*.log"),("All files","*.*")))
  if target:
   try:
    Path(target).write_text(self.logs_as_text(),encoding="utf-8")
    self.logger.info("Session logs saved to %s",target)
   except OSError as e:
    self.logger.error("Saving logs failed: %s",e,exc_info=True)
    messagebox.showerror("Save failed",str(e))
 def clear_logs(self):
  self.history.clear();self.render_logs();self.logger.info("Log view cleared. Disk log preserved.")
 def tk_error(self,etype,error,tb):
  self.logger.log(FAIL,"Unhandled UI exception: %s",error,exc_info=(etype,error,tb))
  self.set_log("UI failure. See Logs tab.")
 def field(self,frame,label,value):
  ttk.Label(frame,text=label).pack();w=ttk.Entry(frame);w.insert(0,value);w.pack(pady=2);return w
 async def scan(self):
  if self.scanning:return
  self.scanning=True
  self.logger.info("BLE scan started: all broadcasts, timeout=10s")
  self.set_log("Scanning all BLE advertisements for 10 seconds...")
  try:
   found=await BleakScanner.discover(timeout=10.0,return_adv=True)
   candidates=[]
   for device,adv in found.values():
    name=(adv.local_name or device.name or "").strip()
    uuids=[str(u).lower() for u in (adv.service_uuids or [])]
    match=SERVICE in uuids or "ROTATOR" in name.upper()
    candidates.append((not match,-int(adv.rssi if adv.rssi is not None else -127),device,name,match))
   candidates.sort(key=lambda item:(item[0],item[1]))
   self.devices=[item[2] for item in candidates]
   for _,_,device,name,match in candidates:
    self.logger.info("SCAN %s name=%r addr=%s", "ROTATOR" if match else "OTHER BLE",name or "(unnamed)",device.address)
   labels=[]
   for _,rssi,device,name,match in candidates:
    prefix="ROTATOR" if match else "OTHER BLE"
    labels.append(f"{prefix}: {name or '(unnamed)'} | RSSI {-rssi} dBm | {device.address}")
   def show():
    self.choice.configure(values=labels)
    self.choice.set("")
    if labels:self.choice.current(0)
   self.ui(show)
   matches=sum(item[4] for item in candidates)
   total=len(candidates)
   self.logger.info("BLE scan completed: %d broadcasts; %d ROTATOR candidates",total,matches)
   if not total:
    self.logger.warning("0 BLE advertisements. Check Windows Bluetooth and ESP32 R5.12 BLE ON.")
    self.set_log("0 BLE broadcasts found. Check Windows Bluetooth, ESP32 R5.12 firmware and BLE ON setting.")
   elif not matches:
    self.logger.warning("%d BLE broadcasts, but 0 ROTATOR name/service matches",total)
    self.set_log(f"{total} BLE devices found, 0 ROTATOR candidates. Other devices are shown for diagnosis; enable BLE on ESP32.")
   else:
    self.set_log(f"{total} BLE devices found; {matches} possible ROTATOR devices. Select ROTATOR and Connect.")
  except Exception as exc:
   self.logger.log(FAIL,"BLE scan failed: %s: %s",type(exc).__name__,exc,exc_info=True)
   self.set_log(f"Bluetooth scan failed ({type(exc).__name__}): {exc}")
  finally:
   self.scanning=False
 async def connect(self,index):
  if self.connecting:
   self.logger.warning("Duplicate Connect ignored: BLE connection/discovery already running")
   self.set_log("Connection still in progress; wait for the log result.")
   return
  if index<0 or index>=len(self.devices):raise ValueError("Scan and select a BLE device")
  self.connecting=True
  device=self.devices[index]
  self.logger.info("BLE connect requested: name=%r address=%s",device.name,device.address)
  try:
   await self.disconnect(force=True)
   self.connection_generation+=1
   generation=self.connection_generation
   self.last_status=None;self.paired=False
   for attempt,use_cache in enumerate((False,True),start=1):
    if attempt>1:
     self.logger.warning("Uncached GATT discovery failed; retrying with Windows cached services")
     await asyncio.sleep(1.0)
    self.logger.info("WinRT connect attempt %d/2: pair=False, use_cached_services=%s",attempt,use_cache)
    client=BleakClient(device,pair=False,timeout=25.0,
     disconnected_callback=lambda cl,g=generation:self.on_disconnect(cl,g),
     winrt={"use_cached_services":use_cache})
    self.client=client
    try:
     await client.connect()
     self.logger.info("GATT connected; services discovered: %s",",".join(str(x.uuid) for x in client.services))
     if client.services.get_service(SERVICE) is None:
      raise RuntimeError("R5.12 control service missing from GATT discovery")
     self.logger.info("R5.12 service found; waiting 1.5 s before initial read")
     self.set_log("GATT found. Checking connection stability before pairing...")
     await asyncio.sleep(1.5)
     if not client.is_connected:raise RuntimeError("Device disconnected before first status read")
     async with self.gatt_lock:blob=await client.read_gatt_char(STATUS)
     payload=blob.decode(errors="replace")
     self.logger.info("Initial unpaired STATUS OK (%d bytes): %s",len(blob),payload[:220])
     self.last_status=json.loads(payload)
     self.logger.info("Read-only BLE session established (cache=%s)",use_cache)
     self.set_log("Read-only link stable. Pair / Authenticate is now available.")
     self.call(self.poll(client,generation))
     return
    except Exception as err:
     self.logger.warning("GATT attempt %d failed: %s: %s",attempt,type(err).__name__,err,exc_info=True)
     try:
      if client.is_connected:await client.disconnect()
     except Exception as cleanup_err:self.logger.warning("GATT cleanup: %s",cleanup_err)
     if self.client is client:self.client=None
     if attempt==2 or not ("Unreachable" in str(err) or "GATT" in str(err)):
      raise
   raise RuntimeError("GATT service discovery failed in both modes")
  finally:
   self.connecting=False
 async def pair_connection(self):
  if self.connecting:
   self.logger.warning("Pair ignored while Connect is still running")
   self.set_log("Wait until Connect completes before pairing")
   return
  client=self.client
  if not client or not client.is_connected:
   self.logger.warning("Cannot pair: device disconnected. Scan/Connect first.")
   self.set_log("Connect to a ROTATOR BLE device first")
   return
  if self.paired:
   self.logger.info("Pair button pressed while this session is already authenticated")
   self.set_log("Already paired for this session.")
   return
  self.logger.info("Starting Windows BLE secure pairing (MITM protected). Await Windows PIN dialog.")
  self.set_log("Pairing: confirm the Windows Bluetooth PIN request...")
  try:
   result=await client.pair()
   self.logger.info("Windows pairing API completed (result=%r, connected=%s)",result,client.is_connected)
   if not client.is_connected:raise RuntimeError("BLE link dropped during pairing")
   async with self.gatt_lock:blob=await client.read_gatt_char(STATUS)
   self.logger.info("Post-pair GATT status read OK (%d bytes)",len(blob))
   self.paired=True
   self.set_log("Secure pairing completed. Motor controls enabled.")
  except Exception as ex:
   self.paired=False
   self.logger.log(FAIL,"Windows BLE secure pairing failed: %s",ex,exc_info=True)
   self.set_log("Pairing failed / disconnected. See Logs tab.")
 def on_disconnect(self,client,generation):
  if generation!=self.connection_generation or (self.client is not None and client is not self.client):return
  self.paired=False
  self.jog=0
  self.jog_token+=1
  self.logger.warning("BLE disconnected unexpectedly: %s. Read-only=%s",client.address,"yes")
  self.set_log("BLE disconnected. See Logs tab.")
 async def disconnect(self,force=False):
  if self.connecting and not force:
   self.logger.warning("Disconnect ignored while Connect is pending")
   self.set_log("Wait until Connect completes, then Disconnect")
   return
  self.jog=0
  self.jog_token+=1
  self.connection_generation+=1
  self.paired=False
  if self.client:
   self.logger.info("BLE disconnect request: %s",self.client.address)
   if self.client.is_connected:
    try:await self.client.write_gatt_char(CMD,b"JOG 0",response=True)
    except Exception:pass
    await self.client.disconnect()
   self.client=None
 async def command_async(self,s):
  if not self.client or not self.client.is_connected:
   self.logger.warning("GATT command rejected: not connected (%s)",s)
   raise RuntimeError("Not connected")
  if not self.paired:
   self.logger.warning("GATT write blocked: pairing required (%s)",s)
   self.set_log("Pair / Authenticate before controlling the motor.")
   return
  if not s.isascii() or len(s)>80:raise ValueError("Invalid command")
  repeated=s.startswith("JOG ") and s!="JOG 0"
  if not repeated:self.logger.info("GATT TX: %s",s)
  try:
   async with self.gatt_lock:
    await self.client.write_gatt_char(CMD,s.encode(),response=True)
    reply=await self.client.read_gatt_char(REPLY)
   decoded=reply.decode(errors="replace")
   level=classify_reply(decoded)
   if not repeated or level>=logging.WARNING:self.logger.log(level,"GATT RX for %s: %s",s,decoded)
   if level>=logging.WARNING:self.set_log("Device reported warning/error. See Logs tab.")
   elif not repeated:self.set_log(decoded)
  except Exception as exc:
   self.logger.log(FAIL,"GATT %s failed: %s",s,exc,exc_info=True)
   self.set_log("GATT command failed. See Logs tab.")
 def command(self,s):self.call(self.command_async(s))
 async def poll(self,client,generation):
  last_error=None
  while self.client is client and generation==self.connection_generation and client.is_connected and self.running:
   try:
    async with self.gatt_lock:blob=await client.read_gatt_char(STATUS)
    obj=json.loads(blob.decode())
    last_error=None
    if self.last_status is None:self.logger.info("First BLE status: role=%s online=%s AZ=%s",obj.get("role"),obj.get("online"),obj.get("az"))
    elif self.last_status.get("fault")!=obj.get("fault"):self.logger.warning("Fault changed: %s -> %s",self.last_status.get("fault"),obj.get("fault"))
    self.last_status=obj
    self.ui(lambda d=obj:self.status.set(f"DEVICE {d.get('role')} | LINK {d.get('online')}\nAZ {d.get('az')}° / TARGET {d.get('target')}°\nFAULT {d.get('fault')} | HOME {d.get('home')} | MOVING {d.get('moving')}"))
   except Exception as e:
    signature=f"{type(e).__name__}: {e}"
    if signature!=last_error:
     self.logger.error("GATT status read/decode failed: %s",signature,exc_info=True)
     self.set_log("Status error. See Logs tab.")
     last_error=signature
    break
   await asyncio.sleep(0.8)
 def go(self):
  try:
   v=int(self.az.get());assert 0<=v<=359
  except (ValueError,AssertionError):return messagebox.showerror("AZ","Enter integer 0–359")
  self.command(f"AZ {v}")
 def set_value(self,key,entry,lo,hi):
  try:
   v=int(entry.get());assert lo<=v<=hi
  except (ValueError,AssertionError):return messagebox.showerror(key,f"Enter {lo}–{hi}")
  self.command(f"{key} {v}")
 def start_jog(self,d):
  if self.jog:return
  self.jog=d;self.jog_token+=1
  self.logger.info("Manual jog started: %s","CW" if d>0 else "CCW")
  self.jog_tick(self.jog_token)
 def jog_tick(self,token):
  if not self.jog or token!=self.jog_token:return
  if not self.paired:
   self.logger.warning("Manual jog blocked (device has not completed authentication)")
   self.jog=0
   return
  self.command("JOG 1" if self.jog>0 else "JOG -1")
  self.root.after(220,lambda t=token:self.jog_tick(t))
 def stop_jog(self):
  if self.jog:
   self.jog=0;self.jog_token+=1
   self.logger.info("Manual jog stopped (JOG 0)")
   if self.paired:self.command("JOG 0")
 def close(self):
  self.stop_jog();self.logger.info("Application closing")
  self.call(self.disconnect())
  self.root.after(450,self.finish_close)
 def finish_close(self):
  self.running=False;self.root.destroy()
  self.loop.call_soon_threadsafe(self.loop.stop)

if __name__=="__main__":
 root=tk.Tk();App(root);root.mainloop()
