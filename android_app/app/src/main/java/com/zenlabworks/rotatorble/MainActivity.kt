package com.zenlabworks.rotatorble
import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.*
import android.bluetooth.le.*
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.widget.*
import java.util.UUID

@SuppressLint("MissingPermission")
@Suppress("DEPRECATION")
class MainActivity: Activity() {
 val service=UUID.fromString("df8268c0-4cc2-4eaa-85dd-3a6159fe0001")
 val cmd=UUID.fromString("df8268c0-4cc2-4eaa-85dd-3a6159fe0002")
 val telemetry=UUID.fromString("df8268c0-4cc2-4eaa-85dd-3a6159fe0003")
 val h=Handler(Looper.getMainLooper())
 lateinit var adapter:BluetoothAdapter
 lateinit var picker:Spinner
 lateinit var result:TextView
 lateinit var target:EditText
 val devices=mutableListOf<BluetoothDevice>()
 val names=mutableListOf<String>()
 lateinit var namesAdapter:ArrayAdapter<String>
 var connection:BluetoothGatt?=null
 var ready=false
 var busy=false
 var jog=0
 val commands=ArrayDeque<String>()
 fun message(s:String){runOnUiThread{result.text=s}}
 fun label(parent:LinearLayout,s:String):TextView {val t=TextView(this);t.text=s;t.textSize=17f;parent.addView(t);return t}
 fun button(parent:LinearLayout,s:String,fn:()->Unit){val b=Button(this);b.text=s;b.setOnClickListener{fn()};parent.addView(b)}
 fun field(parent:LinearLayout,name:String,value:String):EditText {
  label(parent,name);val e=EditText(this);e.inputType=2;e.setSingleLine(true);e.setText(value);parent.addView(e);return e
 }
 override fun onCreate(state:Bundle?){
  super.onCreate(state)
  adapter=(getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
  val body=LinearLayout(this);body.orientation=1;body.setPadding(24,24,24,24)
  val scroll=ScrollView(this);scroll.addView(body);setContentView(scroll)
  label(body,"ROTATOR BLE / REMOTE BLE")
  picker=Spinner(this);namesAdapter=ArrayAdapter(this,android.R.layout.simple_spinner_item,names)
  namesAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
  picker.adapter=namesAdapter;body.addView(picker)
  button(body,"Scan BLE"){scan()}
  button(body,"Connect"){connect()}
  button(body,"Disconnect"){disconnect()}
  result=label(body,"Enable BLE on ESP32 before connecting")
  target=field(body,"Target azimuth 0–359","90")
  button(body,"GO"){val v=target.text.toString().toIntOrNull();if(v!=null && v in 0..359)send("AZ "+v) else message("Invalid azimuth")}
  button(body,"STOP"){stopJog();send("STOP")}
  button(body,"HOME"){send("HOME")}
  val row=LinearLayout(this);body.addView(row)
  for ((name,d) in listOf(Pair("CCW HOLD",-1),Pair("CW HOLD",1))) {
   val b=Button(this);b.text=name;row.addView(b,LinearLayout.LayoutParams(0,-2,1f))
   b.setOnTouchListener{_,event->when(event.actionMasked){
    MotionEvent.ACTION_DOWN->{jog=d;h.post(jogTick);true}
    MotionEvent.ACTION_UP,MotionEvent.ACTION_CANCEL->{stopJog();true}
    else->true}}
  }
  for((key,limits) in listOf(Pair("CURRENT",500..1800),Pair("SPEED",200..6000),Pair("ACCEL",300..4000))){
   val initial=if(key=="CURRENT")"1400" else if(key=="SPEED")"2400" else "1800"
   val input=field(body,key,initial)
   button(body,"Set "+key){val x=input.text.toString().toIntOrNull();if(x!=null && x in limits)send(key+" "+x) else message("Invalid "+key)}
  }
  button(body,"Clear fault"){send("CLEAR")}
  if(Build.VERSION.SDK_INT>=31)requestPermissions(arrayOf(Manifest.permission.BLUETOOTH_SCAN,Manifest.permission.BLUETOOTH_CONNECT),12)
  else requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION),12)
  h.post(poll)
 }
 fun permitted():Boolean = if(Build.VERSION.SDK_INT>=31)
  checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)==PackageManager.PERMISSION_GRANTED &&
  checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)==PackageManager.PERMISSION_GRANTED
 else checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED
 val scanCallback=object:ScanCallback(){
  override fun onScanResult(type:Int,r:ScanResult){
   val name=r.scanRecord?.deviceName ?: r.device.name ?: "Rotator GATT"
   val found=r.scanRecord?.serviceUuids?.any{it.uuid==service}==true || name.contains("ROTATOR",true)
   if(!found)return
   runOnUiThread{if(devices.none{it.address==r.device.address}){
    devices.add(r.device);names.add(name+" "+r.device.address);namesAdapter.notifyDataSetChanged()
   }}
  }
 }
 fun scan(){
  if(!permitted()){message("Bluetooth permissions required");return}
  val scanner=adapter.bluetoothLeScanner?:run{message("Enable Bluetooth");return}
  devices.clear();names.clear();namesAdapter.notifyDataSetChanged()
  scanner.startScan(scanCallback);message("Scanning...")
  h.postDelayed({scanner.stopScan(scanCallback)},7000)
 }
 fun connect(){
  if(!permitted())return
  val i=picker.selectedItemPosition
  if(i !in devices.indices){message("Select a device");return}
  disconnect();val d=devices[i]
  if(d.bondState==BluetoothDevice.BOND_NONE)d.createBond()
  connection=d.connectGatt(this,false,callbacks,BluetoothDevice.TRANSPORT_LE)
 }
 val callbacks=object:BluetoothGattCallback(){
  override fun onConnectionStateChange(g:BluetoothGatt,status:Int,state:Int){
   if(state==BluetoothProfile.STATE_CONNECTED)g.discoverServices()
   else {ready=false;busy=false;jog=0;message("Disconnected")}
  }
  override fun onServicesDiscovered(g:BluetoothGatt,status:Int){
   ready=status==0 && g.getService(service)!=null
   message(if(ready)"GATT ready (secure pairing required)" else "Control service missing")
  }
  override fun onCharacteristicWrite(g:BluetoothGatt,c:BluetoothGattCharacteristic,status:Int){
   busy=false;if(status!=0)message("Write error "+status)
   h.post{pump()}
  }
  override fun onCharacteristicRead(g:BluetoothGatt,c:BluetoothGattCharacteristic,status:Int){
   if(status==0)message(c.value.toString(Charsets.UTF_8));busy=false;h.post{pump()}
  }
  override fun onCharacteristicRead(g:BluetoothGatt,c:BluetoothGattCharacteristic,v:ByteArray,status:Int){
   if(status==0)message(v.toString(Charsets.UTF_8));busy=false;h.post{pump()}
  }
 }
 fun send(s:String){if(!ready){message("Connect first");return};if(commands.size>=8)return;commands.addLast(s);pump()}
 fun pump(){
  val g=connection?:return
  if(!ready||busy||commands.isEmpty())return
  val c=g.getService(service)?.getCharacteristic(cmd)?:return
  c.value=commands.removeFirst().toByteArray(Charsets.US_ASCII)
  c.writeType=BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
  busy=true
  if(!g.writeCharacteristic(c))busy=false
 }
 val jogTick=object:Runnable{override fun run(){
  if(jog!=0){if(ready&&commands.size<2)send("JOG "+jog);h.postDelayed(this,220)}
 }}
 val poll=object:Runnable{override fun run(){
  val g=connection
  if(ready&&!busy&&commands.isEmpty()&&g!=null){
   val c=g.getService(service)?.getCharacteristic(telemetry)
   if(c!=null){busy=true;if(!g.readCharacteristic(c))busy=false}
  }
  h.postDelayed(this,900)
 }}
 fun stopJog(){if(jog!=0){jog=0;h.removeCallbacks(jogTick);commands.removeAll{it.startsWith("JOG ")};send("JOG 0")}}
 fun disconnect(){stopJog();ready=false;busy=false;commands.clear();connection?.disconnect();connection?.close();connection=null}
 override fun onPause(){super.onPause();stopJog()}
 override fun onDestroy(){disconnect();h.removeCallbacksAndMessages(null);super.onDestroy()}
}
