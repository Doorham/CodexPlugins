using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Media;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace CompanyAIHelpers.CodexAnswerChime
{
    static class Program
    {
        static readonly object Gate = new object();
        static readonly Dictionary<string, long> Offsets = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        static readonly HashSet<string> SeenEvents = new HashSet<string>(StringComparer.Ordinal);
        static SoundPlayer CurrentWavePlayer;
        static MemoryStream CurrentWaveStream;
        static string SessionsRoot;

        static void Main(string[] args)
        {
            if (args.Length == 1 && string.Equals(args[0], "--test-sound", StringComparison.OrdinalIgnoreCase))
            {
                Environment.ExitCode = PlayNotificationSound() ? 0 : 2;
                Thread.Sleep(3000);
                return;
            }

            bool created;
            using (var mutex = new Mutex(true, @"Local\CompanyAIHelpers.CodexAnswerChime", out created))
            {
                if (!created) return;
                SessionsRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".codex", "sessions");
                Directory.CreateDirectory(SessionsRoot);

                int tailed = 0;
                foreach (string file in Directory.GetFiles(SessionsRoot, "*.jsonl", SearchOption.AllDirectories))
                {
                    try { Offsets[file] = new FileInfo(file).Length; tailed++; } catch { }
                }

                using (var watcher = new FileSystemWatcher(SessionsRoot, "*.jsonl"))
                {
                    watcher.IncludeSubdirectories = true;
                    watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.Size | NotifyFilters.LastWrite;
                    watcher.Changed += OnFileEvent;
                    watcher.Created += OnFileEvent;
                    watcher.Renamed += delegate(object sender, RenamedEventArgs e) { ProcessFile(e.FullPath); };
                    watcher.EnableRaisingEvents = true;
                    WriteStatus(tailed, true);
                    while (true) Thread.Sleep(60000);
                }
            }
        }

        static void OnFileEvent(object sender, FileSystemEventArgs e) { ProcessFile(e.FullPath); }

        static void ProcessFile(string path)
        {
            lock (Gate)
            {
                try
                {
                    long offset;
                    if (!Offsets.TryGetValue(path, out offset)) offset = 0;
                    using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                    {
                        if (stream.Length < offset) offset = 0;
                        stream.Position = offset;
                        int available = checked((int)(stream.Length - offset));
                        if (available == 0) return;
                        byte[] appended = new byte[available];
                        int total = 0;
                        while (total < appended.Length)
                        {
                            int count = stream.Read(appended, total, appended.Length - total);
                            if (count == 0) break;
                            total += count;
                        }
                        int completeLength = LastCompleteLineLength(appended, total);
                        if (completeLength == 0) return;
                        string text = Encoding.UTF8.GetString(appended, 0, completeLength);
                        foreach (string rawLine in text.Split('\n'))
                        {
                            string line = rawLine.TrimEnd('\r');
                            if (line.Length != 0 && IsFinalAnswerEvent(line) && SeenEvents.Add(Hash(path + "\n" + line)))
                                PlayNotificationSound();
                        }
                        Offsets[path] = offset + completeLength;
                    }
                    if (SeenEvents.Count > 2048) SeenEvents.Clear();
                }
                catch { }
            }
        }

        static int LastCompleteLineLength(byte[] data, int length)
        {
            for (int index = length - 1; index >= 0; index--)
                if (data[index] == (byte)'\n') return index + 1;
            return 0;
        }

        static bool IsFinalAnswerEvent(string line)
        {
            try
            {
                var root = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 }.DeserializeObject(line) as Dictionary<string, object>;
                if (root == null || !EqualsText(root, "type", "event_msg")) return false;
                object payloadValue;
                if (!root.TryGetValue("payload", out payloadValue)) return false;
                var payload = payloadValue as Dictionary<string, object>;
                return payload != null && EqualsText(payload, "type", "agent_message") && EqualsText(payload, "phase", "final_answer");
            }
            catch { return false; }
        }

        static bool EqualsText(Dictionary<string, object> dict, string key, string expected)
        {
            object value;
            return dict.TryGetValue(key, out value) && string.Equals(Convert.ToString(value), expected, StringComparison.Ordinal);
        }

        static string Hash(string text)
        {
            using (var sha = SHA256.Create()) return Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(text)));
        }

        static bool PlayNotificationSound()
        {
            string path = GetConfiguredSoundPath();
            if (string.IsNullOrEmpty(path))
            {
                SystemSounds.Hand.Play();
                return true;
            }
            try
            {
                string extension = Path.GetExtension(path).ToLowerInvariant();
                if (extension == ".wav")
                {
                    if (CurrentWavePlayer != null) CurrentWavePlayer.Stop();
                    if (CurrentWaveStream != null) CurrentWaveStream.Dispose();
                    CurrentWaveStream = BuildPlayableWave(path);
                    CurrentWavePlayer = CurrentWaveStream == null
                        ? new SoundPlayer(path)
                        : new SoundPlayer(CurrentWaveStream);
                    CurrentWavePlayer.Load();
                    CurrentWavePlayer.Play();
                    return true;
                }
                mciSendString("close CodexAnswerChimeSound", null, 0, IntPtr.Zero);
                int opened = mciSendString("open \"" + path + "\" alias CodexAnswerChimeSound", null, 0, IntPtr.Zero);
                if (opened == 0 && mciSendString("play CodexAnswerChimeSound from 0", null, 0, IntPtr.Zero) == 0) return true;
            }
            catch { }
            SystemSounds.Hand.Play();
            return false;
        }

        static MemoryStream BuildPlayableWave(string path)
        {
            byte[] source = File.ReadAllBytes(path);
            if (source.Length < 12 || Encoding.ASCII.GetString(source, 0, 4) != "RIFF" || Encoding.ASCII.GetString(source, 8, 4) != "WAVE")
                throw new InvalidDataException("Invalid WAV file.");

            ushort format = 0;
            ushort channels = 0;
            uint sampleRate = 0;
            ushort bitsPerSample = 0;
            int dataOffset = -1;
            int dataLength = 0;
            int position = 12;
            while (position + 8 <= source.Length)
            {
                string chunk = Encoding.ASCII.GetString(source, position, 4);
                int size = BitConverter.ToInt32(source, position + 4);
                int chunkData = position + 8;
                if (size < 0 || chunkData + size > source.Length) break;
                if (chunk == "fmt " && size >= 16)
                {
                    format = BitConverter.ToUInt16(source, chunkData);
                    channels = BitConverter.ToUInt16(source, chunkData + 2);
                    sampleRate = BitConverter.ToUInt32(source, chunkData + 4);
                    bitsPerSample = BitConverter.ToUInt16(source, chunkData + 14);
                }
                else if (chunk == "data")
                {
                    dataOffset = chunkData;
                    dataLength = size;
                }
                position = chunkData + size + (size & 1);
            }

            if (format == 1) return null;
            if (format != 3 || channels == 0 || sampleRate == 0 || (bitsPerSample != 32 && bitsPerSample != 64) || dataOffset < 0)
                throw new NotSupportedException("Unsupported WAV encoding.");

            int sourceSampleBytes = bitsPerSample / 8;
            int sampleCount = dataLength / sourceSampleBytes;
            byte[] pcm = new byte[sampleCount * 2];
            for (int index = 0; index < sampleCount; index++)
            {
                int input = dataOffset + index * sourceSampleBytes;
                double value = bitsPerSample == 32
                    ? BitConverter.ToSingle(source, input)
                    : BitConverter.ToDouble(source, input);
                if (double.IsNaN(value)) value = 0;
                value = Math.Max(-1.0, Math.Min(1.0, value));
                short sample = (short)Math.Round(value * (value < 0 ? 32768.0 : 32767.0));
                pcm[index * 2] = (byte)(sample & 0xff);
                pcm[index * 2 + 1] = (byte)((sample >> 8) & 0xff);
            }

            MemoryStream output = new MemoryStream(44 + pcm.Length);
            using (BinaryWriter writer = new BinaryWriter(output, Encoding.ASCII, true))
            {
                writer.Write(Encoding.ASCII.GetBytes("RIFF"));
                writer.Write(36 + pcm.Length);
                writer.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
                writer.Write(16);
                writer.Write((ushort)1);
                writer.Write(channels);
                writer.Write(sampleRate);
                writer.Write(sampleRate * channels * 2);
                writer.Write((ushort)(channels * 2));
                writer.Write((ushort)16);
                writer.Write(Encoding.ASCII.GetBytes("data"));
                writer.Write(pcm.Length);
                writer.Write(pcm);
            }
            output.Position = 0;
            return output;
        }

        static string GetConfiguredSoundPath()
        {
            try
            {
                string baseDirectory = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);
                string settingsPath = Path.Combine(baseDirectory, "settings.json");
                if (!File.Exists(settingsPath)) return null;
                var settings = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(settingsPath, Encoding.UTF8)) as Dictionary<string, object>;
                object value;
                if (settings == null || !settings.TryGetValue("SoundFile", out value)) return null;
                string configured = Convert.ToString(value);
                string fullPath = Path.GetFullPath(Path.Combine(baseDirectory, configured));
                if (!fullPath.StartsWith(baseDirectory, StringComparison.OrdinalIgnoreCase)) return null;
                string extension = Path.GetExtension(fullPath).ToLowerInvariant();
                if (extension != ".wav" && extension != ".mp3" && extension != ".wma") return null;
                return File.Exists(fullPath) ? fullPath : null;
            }
            catch { return null; }
        }

        static void WriteStatus(int tailed, bool active)
        {
            try
            {
                var status = new Dictionary<string, object> {
                    { "SessionsRoot", SessionsRoot }, { "StartedAt", DateTime.Now.ToString("o") },
                    { "ProcessId", Process.GetCurrentProcess().Id }, { "ExistingFilesTailedFromEnd", tailed },
                    { "WatcherActive", active }
                };
                string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "listener-status.json");
                File.WriteAllText(path, new JavaScriptSerializer().Serialize(status), new UTF8Encoding(false));
            }
            catch { }
        }

        [DllImport("winmm.dll", CharSet = CharSet.Unicode)] static extern int mciSendString(string command, StringBuilder returnValue, int returnLength, IntPtr callback);
    }
}
