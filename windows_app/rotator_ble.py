"""F11 Windows BLE client for both ROTATOR and REMOTE (R5.12 GATT)."""
import asyncio
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from bleak import BleakClient, BleakScanner

SERVICE="df8268c0-4cc2-4eaa-85dd-3a6159fe0001"
CMD="df8268c0-4cc2-4eaa-85dd-3a6159fe0002"
STATUS="df8268c0-4cc2-4eaa-85dd-3a6159fe0003"
REPLY="df8268c0-4cc2-4eaa-85dd-3a6159fe0004"

class App:
 def __init__(self,root):
  self.root=root;root.title("Rotator BLE — REMOTE / ROTATOR");root.geometry("560x600")
  self.loop=asyncio.new_event_loop();threading.Thread(target=self._worker,daemon=True).start()
  self.devices=[];self.client=None;self.running=True;self.jog=0;self.scanning=False
  frame=ttk.Frame(root,padding=16);frame.pack(fill="both",expand=True)
  ttk.Label(frame,text="ROTATOR BLE / REMOTE BLE",font=("Segoe UI",16,"bold")).pack()
  self.choice=ttk.Combobox(frame,state="readonly",width=48);self.choice.pack(fill="x",pady=8)
  bar=ttk.Frame(frame);bar.pack()
  ttk.Button(bar,text="Scan",command=lambda:self.call(self.scan())).pack(side="left")
  ttk.Button(bar,text="Connect",command=lambda:self.call(self.connect(self.choice.current()))).pack(side="left")
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
  self.log=tk.StringVar(value="Pair device through Windows Bluetooth if prompted.")
  ttk.Label(frame,textvariable=self.log,wraplength=490).pack(pady=8)
  root.bind("<FocusOut>",lambda e:self.stop_jog());root.protocol("WM_DELETE_WINDOW",self.close)
 def _worker(self):
  asyncio.set_event_loop(self.loop);self.loop.run_forever()
 def call(self,coro):
  future=asyncio.run_coroutine_threadsafe(coro,self.loop)
  def done(f):
   try:f.result()
   except Exception as e:self.set_log(str(e))
  future.add_done_callback(done)
 def ui(self,func):self.root.after(0,func)
 def set_log(self,msg):self.ui(lambda:self.log.set(msg))
 def field(self,frame,label,value):
  ttk.Label(frame,text=label).pack();w=ttk.Entry(frame);w.insert(0,value);w.pack(pady=2);return w
 async def scan(self):
  if self.scanning:return
  self.scanning=True
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
   if not total:
    self.set_log("0 BLE broadcasts found. Check Windows Bluetooth, ESP32 R5.12 firmware and BLE ON setting.")
   elif not matches:
    self.set_log(f"{total} BLE devices found, 0 ROTATOR candidates. Other devices are shown for diagnosis; enable BLE on ESP32.")
   else:
    self.set_log(f"{total} BLE devices found; {matches} possible ROTATOR devices. Select ROTATOR and Connect.")
  except Exception as exc:
   self.set_log(f"Bluetooth scan failed ({type(exc).__name__}): {exc}")
  finally:
   self.scanning=False
 async def connect(self,index):
  if index<0 or index>=len(self.devices):raise ValueError("Scan and select a BLE device")
  await self.disconnect()
  self.client=BleakClient(self.devices[index],pair=True,timeout=30.0)
  await self.client.connect()
  if self.client.services.get_service(SERVICE) is None:raise RuntimeError("R5.12 control GATT not found")
  self.set_log("Secure GATT connected")
  self.call(self.poll())
 async def disconnect(self):
  self.jog=0
  if self.client:
   if self.client.is_connected:
    try:await self.client.write_gatt_char(CMD,b"JOG 0",response=True)
    except Exception:pass
    await self.client.disconnect()
   self.client=None
 async def command_async(self,s):
  if not self.client or not self.client.is_connected:raise RuntimeError("Not connected")
  if not s.isascii() or len(s)>80:raise ValueError("Invalid command")
  await self.client.write_gatt_char(CMD,s.encode(),response=True)
  reply=await self.client.read_gatt_char(REPLY)
  self.set_log(reply.decode(errors="replace"))
 def command(self,s):self.call(self.command_async(s))
 async def poll(self):
  while self.client and self.client.is_connected and self.running:
   try:
    blob=await self.client.read_gatt_char(STATUS)
    obj=json.loads(blob.decode())
    self.ui(lambda d=obj:self.status.set(f"DEVICE {d.get('role')} | LINK {d.get('online')}\nAZ {d.get('az')}° / TARGET {d.get('target')}°\nFAULT {d.get('fault')} | HOME {d.get('home')} | MOVING {d.get('moving')}"))
   except Exception as e:self.set_log(f"Status: {e}");break
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
  self.jog=d
  self.jog_tick()
 def jog_tick(self):
  if not self.jog:return
  self.command("JOG 1" if self.jog>0 else "JOG -1")
  self.root.after(220,self.jog_tick)
 def stop_jog(self):
  if self.jog:self.jog=0;self.command("JOG 0")
 def close(self):
  self.running=False;self.stop_jog();self.call(self.disconnect());self.root.after(200,self.root.destroy)

if __name__=="__main__":
 root=tk.Tk();App(root);root.mainloop()
