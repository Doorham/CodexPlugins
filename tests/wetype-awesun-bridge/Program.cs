using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

// Runs the real receiver TextChanged and clipboard retry paths with an in-memory
// clipboard sink. No real clipboard, focus transfer or recording is touched.
internal static class BridgeTests {
    static readonly BindingFlags Hidden=BindingFlags.Instance|BindingFlags.NonPublic;
    static object Field(VoiceBridge bridge,string name){return typeof(VoiceBridge).GetField(name,Hidden).GetValue(bridge);}
    static void Call(VoiceBridge bridge,string name){typeof(VoiceBridge).GetMethod(name,Hidden).Invoke(bridge,null);}
    static void Require(bool condition,string label){if(!condition)throw new Exception(label);}
    [STAThread] static int Main() {
        Require(VoiceBridge.IsRemoteClient("AweSun",null,null,null,null),"international client");
        Require(VoiceBridge.IsRemoteClient("SUNLOGINCLIENT.exe",null,null,null,null),"localized client and case normalization");
        Require(VoiceBridge.IsRemoteClient("RenamedPortable","SunloginClient.exe",null,null,null),"renamed client original filename");
        Require(VoiceBridge.IsRemoteClient("RenamedPortable","AweSun.exe",null,null,null),"renamed international client");
        Require(VoiceBridge.IsRemoteClient("DifferentBuild",null,"贝锐向日葵","向日葵远程控制64位","上海贝锐信息科技股份有限公司"),"localized product identity");
        Require(VoiceBridge.IsRemoteClient("DifferentBuild",null,"Sunlogin","Remote Control Client","Oray Inc."),"English product identity");
        Require(!VoiceBridge.IsRemoteClient("SunloginClientFake",null,null,null,null),"no broad process prefix match");
        Require(!VoiceBridge.IsRemoteClient("Editor",null,"向日葵","Remote Control","Unrelated vendor"),"unrelated product cannot steal focus");
        Require(!VoiceBridge.IsRemoteClient("Editor",null,null,"Example remote computer",null),"remote computer title is not identity");
        Require(!VoiceBridge.IsRemoteClient("AweSun.unrelated",null,null,null,null),"unrelated extension is not a client alias");
        foreach(string name in new[]{"SunloginService","sunlogin_guard","SunloginUpdate"})
            Require(!VoiceBridge.IsRemoteClient(name,"SunloginClient.exe","Sunlogin","Remote Control","Oray"),"service/guard/updater excluded");
        var writes=new List<string>();
        using(var stop=new EventWaitHandle(false,EventResetMode.AutoReset)) {
            var bridge=new VoiceBridge(stop,value=>writes.Add(value));
            var box=(TextBox)Field(bridge,"text");
            box.Text="第一段\r\n第二段";
            Require(writes.Count==1&&writes[0]==box.Text,"idle late commit must copy synchronously with formatting");
            Call(bridge,"Release");
            Require(writes.Count==1&&box.TextLength==0,"clearing receiver must not overwrite clipboard");
            box.Text="窗口关闭后提交";
            Require(writes.Count==2&&writes[1]==box.Text,"late text after release must still be captured");
            Call(bridge,"Release");
            var phase=typeof(VoiceBridge).GetField("phase",Hidden);
            phase.SetValue(bridge,Enum.Parse(phase.FieldType,"Receiving"));
            box.Text="中途切走";
            ((Form)Field(bridge,"receiver")).Hide();
            Require(box.Text=="中途切走","hide must retain text");
            box.Text+="，再切回来";
            Require(writes[writes.Count-1]==box.Text,"returning must copy latest complete buffer");
            bridge.ExitThread();
        }
        int attempts=0;
        using(var stop=new EventWaitHandle(false,EventResetMode.AutoReset)) {
            var bridge=new VoiceBridge(stop,value=>{if(++attempts==1)throw new ExternalException();});
            var box=(TextBox)Field(bridge,"text");
            box.Text="占用时保留";
            Require((bool)Field(bridge,"copyPending")&&box.TextLength>0,"busy clipboard must retain pending text");
            Call(bridge,"CopyOutput");
            Require(attempts==2&&!(bool)Field(bridge,"copyPending"),"retry must publish pending text");
            bridge.ExitThread();
        }
        TextBox reentrantBox=null;
        writes.Clear();
        using(var stop=new EventWaitHandle(false,EventResetMode.AutoReset)) {
            var bridge=new VoiceBridge(stop,value=>{writes.Add(value);if(writes.Count==1)reentrantBox.Text="最终排版";});
            reentrantBox=(TextBox)Field(bridge,"text");
            reentrantBox.Text="初稿";
            Require((bool)Field(bridge,"copyPending"),"nested commit must remain pending");
            Call(bridge,"CopyOutput");
            Require(writes.Count==2&&writes[1]=="最终排版","nested commit must publish newest text");
            bridge.ExitThread();
        }
        Require(VoiceBridge.WantsReceiver(true,false,false,false),"enter AweSun");
        Require(VoiceBridge.WantsReceiver(false,true,false,true),"receiver retains context");
        Require(VoiceBridge.WantsReceiver(false,false,true,true),"voice overlay retains AweSun context");
        Require(!VoiceBridge.WantsReceiver(false,false,false,true),"external app must hide receiver");
        Require(!VoiceBridge.WantsReceiver(false,false,true,false),"unrelated voice session must not steal focus");
        Console.WriteLine("PASS: remote client identity, renamed/localized builds, service exclusions, late commit, formatting, immediate copy, empty release, retained buffer, busy clipboard retry, nested commit, focus policy.");
        return 0;
    }
}
