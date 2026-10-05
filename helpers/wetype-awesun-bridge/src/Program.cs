using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// Observe voice UI and acquire one receiver. No keyboard hooks or synthetic keys.
internal sealed class VoiceBridge : ApplicationContext {
    enum Phase { Idle, Receiving, Finishing, CopyFailed }
    delegate bool WindowProc(IntPtr hwnd,IntPtr unused);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr SetActiveWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr SetFocus(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr GetFocus();
    [DllImport("user32.dll",SetLastError=true)] static extern bool AttachThreadInput(uint current,uint foreground,bool attach);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll",SetLastError=true)] static extern IntPtr SendMessageTimeout(IntPtr hwnd,uint message,IntPtr wParam,IntPtr lParam,uint flags,uint timeout,out IntPtr result);
    [DllImport("user32.dll",SetLastError=true)] static extern bool OpenClipboard(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool CloseClipboard();
    [DllImport("user32.dll")] static extern IntPtr GetClipboardData(uint format);
    [DllImport("kernel32.dll")] static extern IntPtr GlobalLock(IntPtr memory);
    [DllImport("kernel32.dll")] static extern bool GlobalUnlock(IntPtr memory);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
    [DllImport("user32.dll")] static extern bool EnumWindows(WindowProc proc,IntPtr unused);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd,StringBuilder text,int count);
    readonly EventWaitHandle stop;
    readonly Form receiver=new Form();
    readonly TextBox text=new TextBox();
    readonly NotifyIcon tray=new NotifyIcon();
    readonly System.Windows.Forms.Timer tick=new System.Windows.Forms.Timer();
    readonly Action<string> publishClipboard;
    Phase phase=Phase.Idle;
    IntPtr target,lastExternalAweSun;
    IntPtr lastForeground;
    bool attemptedFocusForEntry,copyPending;
    bool copying;
    DateTime nextCopy;
    string output="",copiedOutput="";
    int copyAttempts;
    volatile bool focusTransferRunning;
    uint identityPid;
    string identityName="";
    bool identityMatch;
    DateTime nextIdentityCheck;

    [STAThread] static int Main(string[] args) {
        string stopName="Local\\WeTypeAweSunBridge_Stop_"+Environment.UserName;
        if(args.Length==1&&args[0]=="--stop") {
            try { using(var signal=EventWaitHandle.OpenExisting(stopName))signal.Set();return 0; }
            catch(WaitHandleCannotBeOpenedException){return 1;}
        }
        if(args.Length!=0)return 3;
        bool created;
        using(var singleton=new Mutex(true,"Local\\WeTypeAweSunBridge_Single_"+Environment.UserName,out created)) {
            if(!created)return 2;
            using(var signal=new EventWaitHandle(false,EventResetMode.AutoReset,stopName))
                Application.Run(new VoiceBridge(signal));
        }
        return 0;
    }
    internal VoiceBridge(EventWaitHandle signal,Action<string> publisher=null) {
        stop=signal;
        publishClipboard=publisher??WriteClipboard;
        receiver.FormBorderStyle=FormBorderStyle.None;receiver.ShowInTaskbar=false;
        receiver.StartPosition=FormStartPosition.Manual;receiver.Opacity=0.01;
        receiver.SetBounds(Screen.PrimaryScreen.WorkingArea.Right-160,Screen.PrimaryScreen.WorkingArea.Bottom-48,150,40);
        text.Multiline=true;text.Dock=DockStyle.Fill;receiver.Controls.Add(text);
        text.TextChanged+=(s,e)=>{
            // The control remains alive after Release. Accept a final commit even
            // when WeType has already hidden its voice window and we are idle.
            if(text.TextLength>0) {
                output=text.Text;copyPending=true;copyAttempts=0;nextCopy=DateTime.UtcNow;
                Log("receiver_text_changed characters="+output.Length);
                CopyOutput();
            }
        };
        var menu=new ContextMenuStrip();
        menu.Items.Add("重试复制",null,(s,e)=>{
            if(copyPending){copyAttempts=0;nextCopy=DateTime.UtcNow;}
        });
        menu.Items.Add("退出",null,(s,e)=>ExitThread());
        tray.Icon=publisher==null?(Icon.ExtractAssociatedIcon(Application.ExecutablePath)??SystemIcons.Application):SystemIcons.Application;
        tray.Text="微信语音输入远程状态监听板";
        tray.ContextMenuStrip=menu;
        tick.Interval=30;tick.Tick+=Update;
        if(publisher==null){tray.Visible=true;tick.Start();Log("persistent_voice_monitor_ready no_keyboard_hooks");}
    }
    static string ProcessName(IntPtr hwnd) {
        uint pid;GetWindowThreadProcessId(hwnd,out pid);
        try { using(var process=Process.GetProcessById((int)pid))return process.ProcessName; }
        catch{return "";}
    }
    static bool ClientName(string value) {
        string name=value??"";
        int slash=Math.Max(name.LastIndexOf('/'),name.LastIndexOf('\\'));
        if(slash>=0)name=name.Substring(slash+1);
        if(name.EndsWith(".exe",StringComparison.OrdinalIgnoreCase))name=name.Substring(0,name.Length-4);
        return name.Equals("AweSun",StringComparison.OrdinalIgnoreCase)||
            name.Equals("SunloginClient",StringComparison.OrdinalIgnoreCase);
    }
    static bool Contains(string value,string part) {
        return (value??"").IndexOf(part,StringComparison.OrdinalIgnoreCase)>=0;
    }
    internal static bool IsRemoteClient(string processName,string originalFilename,
        string productName,string description,string companyName) {
        // A remote computer's title/name is never an application identity.
        if(ClientName(processName))return true;
        if(Contains(processName,"service")||Contains(processName,"guard")||Contains(processName,"update"))return false;
        if(ClientName(originalFilename))return true;
        bool brand=Contains(productName,"AweSun")||Contains(productName,"Sunlogin")||Contains(productName,"向日葵");
        bool client=Contains(description,"remote control")||Contains(description,"remote desktop")||Contains(description,"远程控制");
        bool vendor=Contains(companyName,"Oray")||Contains(companyName,"贝锐");
        return brand&&client&&vendor;
    }
    bool RemoteClient(IntPtr hwnd,string processName) {
        if(ClientName(processName))return true;
        uint pid;GetWindowThreadProcessId(hwnd,out pid);
        DateTime now=DateTime.UtcNow;
        if(pid==identityPid&&processName==identityName&&now<nextIdentityCheck)return identityMatch;
        identityPid=pid;identityName=processName;identityMatch=false;
        nextIdentityCheck=now.AddSeconds(2);
        // Cache metadata, including failures, rather than reading an EXE every 30ms.
        // Periodic refresh also prevents a reused PID from retaining old identity.
        try {
            using(var process=Process.GetProcessById((int)pid)) {
                var module=process.MainModule;
                if(module==null)return false;
                var info=FileVersionInfo.GetVersionInfo(module.FileName);
                identityMatch=IsRemoteClient(processName,info.OriginalFilename,
                    info.ProductName,info.FileDescription,info.CompanyName);
            }
        } catch(InvalidOperationException){}catch(System.ComponentModel.Win32Exception){}
        catch(ArgumentException){}catch(IOException){}catch(UnauthorizedAccessException){}
        catch(System.Security.SecurityException){}
        return identityMatch;
    }
    static bool WeType(IntPtr hwnd){return ProcessName(hwnd).StartsWith("wetype",StringComparison.OrdinalIgnoreCase);}
    static bool VoiceVisible() {
        bool found=false;
        EnumWindows((hwnd,unused)=>{
            if(!IsWindowVisible(hwnd))return true;
            var title=new StringBuilder(128);GetWindowText(hwnd,title,title.Capacity);
            if(title.ToString()=="语音输入"&&WeType(hwnd)){found=true;return false;}return true;
        },IntPtr.Zero);return found;
    }
    bool AcquireReceiverOnce() {
        IntPtr foreground=GetForegroundWindow();
        uint ignored;
        uint foregroundThread=GetWindowThreadProcessId(foreground,out ignored);
        uint currentThread=GetCurrentThreadId();
        IntPtr response;
        // Refuse to couple input queues to a foreground window that is unresponsive.
        if(foreground!=IntPtr.Zero&&SendMessageTimeout(foreground,0,IntPtr.Zero,IntPtr.Zero,2,100,out response)==IntPtr.Zero) {
            Log("focus_transfer_skipped_foreground_unresponsive");return false;
        }
        bool attached=false;
        focusTransferRunning=true;
        using(var watchdog=new System.Threading.Timer(s=>{
            if(focusTransferRunning) {
                Log("focus_transfer_watchdog_exit");
                Process.GetCurrentProcess().Kill();
            }
        },null,2000,Timeout.Infinite)) {
            try {
                if(foregroundThread!=0&&foregroundThread!=currentThread) {
                    attached=AttachThreadInput(currentThread,foregroundThread,true);
                    if(!attached){Log("focus_input_attach_failed error="+Marshal.GetLastWin32Error());return false;}
                }
                receiver.TopMost=true;receiver.Show();
                SetForegroundWindow(receiver.Handle);
                SetActiveWindow(receiver.Handle);
                SetFocus(text.Handle);
            } finally {
                if(attached&&!AttachThreadInput(currentThread,foregroundThread,false)) {
                    Log("focus_input_detach_failed_exit");
                    Process.GetCurrentProcess().Kill();
                }
                focusTransferRunning=false;
            }
        }
        bool foregroundVerified=GetForegroundWindow()==receiver.Handle;
        bool textFocusVerified=GetFocus()==text.Handle;
        Log("focus_transfer foreground="+foregroundVerified+" textbox="+textFocusVerified+" input_queues_detached=true");
        return foregroundVerified&&textFocusVerified;
    }
    internal static bool WantsReceiver(bool aweSun,bool ownReceiver,bool weType,bool lastExternalAweSun) {
        return aweSun||ownReceiver||(weType&&lastExternalAweSun);
    }
    void Update(object sender,EventArgs e) {
        if(stop.WaitOne(0)){ExitThread();return;}
        if(focusTransferRunning)return;
        DateTime now=DateTime.UtcNow;
        IntPtr foreground=GetForegroundWindow();
        string process=ProcessName(foreground);
        bool aweSun=RemoteClient(foreground,process);
        bool weType=process.StartsWith("wetype",StringComparison.OrdinalIgnoreCase);
        bool ownReceiver=foreground==receiver.Handle;
        bool changed=foreground!=lastForeground;
        lastForeground=foreground;
        if(aweSun)lastExternalAweSun=foreground;
        else if(!weType&&!ownReceiver)lastExternalAweSun=IntPtr.Zero;
        bool voiceVisible=VoiceVisible();
        if(copyPending&&copyAttempts<20&&now>=nextCopy)CopyOutput();

        // Listening starts wherever voice was opened. AweSun is only a display/
        // focus condition; it never gates recording detection or clipboard output.
        if(phase==Phase.Idle) {
            if(!voiceVisible)return;
            text.Clear();attemptedFocusForEntry=false;phase=Phase.Receiving;
            Log("voice_monitor_started receiver_suspended");
        }
        if(phase==Phase.Receiving) {
            if(!voiceVisible) {
                phase=Phase.Finishing;
                Log("voice_ended_finish_without_delay");
            } else {
                bool wants=WantsReceiver(aweSun,ownReceiver,weType,lastExternalAweSun!=IntPtr.Zero);
                if(!wants) {
                    attemptedFocusForEntry=false;
                    if(receiver.Visible){receiver.Hide();receiver.TopMost=false;Log("receiver_hidden_outside_awesun buffer_retained");}
                } else if(!ownReceiver&&((aweSun&&changed)||(!receiver.Visible&&!attemptedFocusForEntry))) {
                    attemptedFocusForEntry=true;
                    target=aweSun?foreground:lastExternalAweSun;
                    Log("awesun_context_entered activate_receiver");
                    if(AcquireReceiverOnce())Log("receiver_activated_buffer_retained");
                    else {receiver.Hide();Log("receiver_activation_failed");}
                    receiver.TopMost=false;
                    lastForeground=GetForegroundWindow();
                }
                return;
            }
        }
        if(phase==Phase.Finishing||phase==Phase.CopyFailed) {
            if(copying)return;
            if(copyPending) {
                if(copyAttempts>=20)phase=Phase.CopyFailed;
                return;
            }
            Log("completed_immediately characters="+text.TextLength);Release();
        }
    }
    bool ClipboardMatches(string value) {
        if(!OpenClipboard(receiver.Handle))return false;
        try {
            IntPtr memory=GetClipboardData(13);
            if(memory==IntPtr.Zero)return false;
            IntPtr pointer=GlobalLock(memory);
            if(pointer==IntPtr.Zero)return false;
            try{return Marshal.PtrToStringUni(pointer)==value;}
            finally{GlobalUnlock(memory);}
        } finally {CloseClipboard();}
    }
    void CopyOutput() {
        if(copying)return;
        copying=true;
        string received=output;
        try {
            publishClipboard(received);
            copiedOutput=received;copyPending=output!=received;
            Log("clipboard_verified characters="+copiedOutput.Length);
        } catch(ExternalException) {
            nextCopy=DateTime.UtcNow.AddMilliseconds(200);
            if(++copyAttempts==20) {
                Log("clipboard_failed_text_retained");
                tray.ShowBalloonTip(2500,"微信语音","复制失败，文字仍在承接板，可从托盘重试。",ToolTipIcon.Warning);
            }
        } finally {copying=false;}
    }
    void WriteClipboard(string received) {
        var clipboardData=new DataObject();
        clipboardData.SetText(received,TextDataFormat.UnicodeText);
        Clipboard.SetDataObject(clipboardData,true,0,0);
        if(!ClipboardMatches(received))throw new ExternalException();
    }
    void Release() {
        bool restoreFocus=GetForegroundWindow()==receiver.Handle;
        IntPtr restore=target;phase=Phase.Idle;target=IntPtr.Zero;
        copyPending=false;copyAttempts=0;output="";copiedOutput="";
        attemptedFocusForEntry=false;
        receiver.TopMost=false;receiver.Hide();text.Clear();
        if(restoreFocus&&restore!=IntPtr.Zero)SetForegroundWindow(restore);
    }
    static void Log(string state) {
        try {File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"运行状态.log"),
            DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff")+" "+state+Environment.NewLine,Encoding.UTF8);}
        catch(IOException){}catch(UnauthorizedAccessException){}
    }
    protected override void ExitThreadCore() {
        tick.Stop();tick.Dispose();
        Release();tray.Visible=false;tray.Dispose();receiver.Dispose();base.ExitThreadCore();
    }
}
