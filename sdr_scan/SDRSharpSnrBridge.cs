// F09 SDR# VisualSNR sender. Build against the SDK matching *your* SDR# version.
// Keeps SDR# read-only; it never tunes the radio, starts a transmission, or
// controls the antenna. Only emits local UDP; no network listener.
using System;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
using SDRSharp.Common;

namespace Zenlabworks.RotatorSnr
{
    public sealed class RotatorSnrPlugin : ISharpPlugin
    {
        private ISharpControl _control;
        private Timer _timer;
        private UdpClient _udp;
        private PropertyInfo _snrProperty;
        private readonly IPEndPoint _destination = new IPEndPoint(IPAddress.Loopback, 47291);

        public string DisplayName => "Zenlabworks Rotator SNR Bridge";
        public bool HasGui => false;
        public UserControl GuiControl => null;

        public void Initialize(ISharpControl control)
        {
            _control = control ?? throw new ArgumentNullException(nameof(control));
            // VisualSNR is SDK/version-specific: explicitly decline output if
            // the property is missing, instead of fabricating a signal level.
            _snrProperty = control.GetType().GetProperty("VisualSNR",
                BindingFlags.Public | BindingFlags.Instance);
            if (_snrProperty == null)
            {
                // A later SDK may expose VisualSNR only on its interface.
                foreach (var iface in control.GetType().GetInterfaces())
                {
                    var prop = iface.GetProperty("VisualSNR");
                    if (prop != null) { _snrProperty = prop; break; }
                }
            }
            _udp = new UdpClient(AddressFamily.InterNetwork);
            _timer = new Timer { Interval = 200 };
            _timer.Tick += Tick;
            _timer.Start();
        }

        private void Tick(object sender, EventArgs e)
        {
            if (_control == null || _udp == null || _snrProperty == null)
                return;
            try
            {
                // WinForms timer accesses SDR# properties on the GUI thread.
                if (!_control.IsPlaying) return;
                double snr = Convert.ToDouble(_snrProperty.GetValue(_control));
                if (double.IsNaN(snr) || double.IsInfinity(snr) || snr < -60 || snr > 120)
                    return;
                long frequency = _control.Frequency;
                var payload = "{\"snr_db\":" +
                    snr.ToString("R", System.Globalization.CultureInfo.InvariantCulture) +
                    ",\"frequency_hz\":" + frequency.ToString() +
                    ",\"playing\":true}";
                var bytes = Encoding.UTF8.GetBytes(payload);
                _udp.Send(bytes, bytes.Length, _destination);
            }
            catch (Exception)
            {
                // A stale SDR# SDK/property must not take down the receiver;
                // missing metrics instead make the rotator sweep fail closed.
            }
        }

        public void Close()
        {
            if (_timer != null)
            {
                _timer.Stop();
                _timer.Tick -= Tick;
                _timer.Dispose();
                _timer = null;
            }
            _udp?.Dispose();
            _udp = null;
            _control = null;
        }
    }
}
