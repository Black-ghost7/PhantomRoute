<div dir="rtl">

# PhantomRoute — نسخة Kali / Debian / Ubuntu

تدوير الهوية عبر Tor مع Kill Switch وتغيير MAC و Hostname واستعادة كاملة للنظام.

## المتطلبات

- Kali أو Debian أو Ubuntu (أو مشتقاتها)، مع `systemd` و `NetworkManager`
- صلاحيات Root (`sudo`)
- Python 3.8 أو أحدث
- الحزم: `tor` `curl` `macchanger` `iptables`

## التثبيت

```bash
chmod +x install.sh
./install.sh
source ~/.bashrc
```

أو يدوياً:

```bash
sudo apt update
sudo apt install -y tor curl macchanger iptables iproute2 python3
sudo python3 phantomroute.py
```

> أثناء تثبيت `macchanger` قد يسألك: *هل تريد تغيير MAC تلقائياً عند الإقلاع؟* اختر **No**.

## الاستخدام

```bash
phantomroute                    # تشغيل
phantomroute --interval 30      # تدوير أسرع
phantomroute --no-mac           # بدون تغيير MAC
phantomroute --no-killswitch    # بدون iptables
phantomroute --status           # عرض الحالة
phantomroute --panic            # استعادة طارئة
```

## ما الذي يحدث عند التشغيل؟

1. حفظ الحالة الأصلية (MAC، Hostname، `resolv.conf`، `torrc`، حالة الخدمات) في `/var/lib/phantomroute/state.json` (صلاحيات root فقط).
2. معرفة بلدك الحقيقي لاختيار بلدان خروج قريبة منه.
3. تغيير MAC و Hostname.
4. تفعيل Kill Switch في سلسلتين خاصتين `PHANTOMR_OUT` (IPv4) و`PHANTOMR_OUT6` (IPv6): يُسمح فقط بـ loopback و DHCP ومستخدم Tor (`debian-tor`).
5. توجيه DNS إلى `127.0.0.1` (منفذ DNS الخاص بـ Tor).
6. تشغيل Tor وانتظار اكتماله، ثم تدوير بلد الخروج كل `--interval` ثانية (10 كحد أدنى) دون إعادة تشغيل Tor، مع فحص الاتصال وإعادة فرض إعدادات DNS دورياً.

## ضبط البرامج

الأداة لا تحوّل حركة النظام تلقائياً. اضبط برامجك على **SOCKS5 ‏`127.0.0.1:9050`** أو استخدم:

```bash
torsocks curl https://check.torproject.org/api/ip
proxychains4 firefox        # بعد ضبط proxychains على socks5 127.0.0.1 9050
```

أي اتصال خارج Tor يُحجب أثناء التشغيل (ما لم تستخدم `--no-killswitch`).

## الإيقاف والاستعادة

اضغط `Ctrl + C`. الأداة تعيد كل شيء إلى حالته الأصلية ثم تختبر DNS والاتصال.
عند الانهيار: `sudo phantomroute --panic`.

## إزالة التثبيت

```bash
./uninstall.sh
```

</div>
