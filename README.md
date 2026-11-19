<div dir="rtl">

# 👻 PhantomRoute

أداة لتدوير الهوية الشبكية عبر شبكة **Tor** مع استعادة مضمونة لإعدادات النظام عند الإيقاف.
تعمل على **Kali / Debian / Ubuntu** (سطح المكتب) وعلى **Android عبر Termux**.

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Kali%20%7C%20Debian%20%7C%20Termux-green)](#-المنصات-المدعومة)

---

## 📋 المميزات

- 🌍 **تدوير بلد الخروج (Exit Node):** اختيار بلد قريب جغرافياً من بلدك الحقيقي كل فترة زمنية (الافتراضي 60 ثانية).
- 🔒 **تغيير MAC Address** للواجهة النشطة (نسخة Kali).
- 🎭 **تغيير اسم الجهاز (Hostname)** إلى اسم عشوائي (نسخة Kali).
- 🛡️ **Kill Switch** عبر سلاسل iptables/ip6tables خاصة بالأداة فقط (`PHANTOMR_OUT`) بدون المساس بباقي القواعد؛ يسمح فقط بـ loopback و DHCP وبرنامج Tor نفسه (نسخة Kali).
- 🔐 **توجيه DNS إلى Tor** لتقليل تسريب الطلبات (نسخة Kali).
- 💾 **حفظ الحالة الأصلية** في `state.json` لاستعادتها بعد أي انهيار عبر `--panic`.
- 🔑 **منفذ التحكم في Tor محمي بكلمة مرور عشوائية** لكل جلسة.
- ⚡ **تبديل بلد الخروج دون إعادة تشغيل Tor** (عبر ControlPort).
- 📊 **تقرير جلسة** يتضمن عدد الفحوصات وعدد التدويرات والدول المستخدمة.

---

## 📱 المنصات المدعومة

| النسخة | المنصة | صلاحيات | MAC | Kill Switch | DNS |
|---|---|---|---|---|---|
| `PhantomRoute-Kali` | Kali / Debian / Ubuntu | Root | ✅ | ✅ | ✅ |
| `PhantomRoute-Termux` | Android (Termux) | بدون Root | ❌ | ❌ | محدود |

---

## 📁 هيكل المشروع

```
PhantomRoute/
├── PhantomRoute-Kali/        # نسخة سطح المكتب
│   ├── phantomroute.py
│   ├── install.sh
│   └── README.md
├── PhantomRoute-Termux/      # نسخة الهاتف
│   ├── phantomroute.py
│   ├── install.sh
│   └── README.md
├── phantomroute              # المشغّل الموحّد (يكتشف المنصة تلقائياً)
├── README.md
└── .gitignore
```

---

## ⬇️ التنزيل

```bash
git clone https://github.com/Black-ghost7/PhantomRoute.git
cd PhantomRoute
```

أو نزّل الملف المضغوط من زر **Code ← Download ZIP** ثم فك الضغط.

---

## 🛠️ التثبيت

### على Kali / Debian / Ubuntu

```bash
cd PhantomRoute-Kali
chmod +x install.sh
./install.sh
source ~/.bashrc
```

يثبّت السكربت الحزم `tor curl macchanger iptables` وينشئ الأمر `phantomroute`.

### على Android (Termux)

```bash
cd PhantomRoute-Termux
chmod +x install.sh
./install.sh
```

### المشغّل الموحّد (اختياري)

سكربت التثبيت ينشئ الأمر `phantomroute` أصلاً. هذا المشغّل الموحّد اختياري، ويفيد فقط إن ثبّتّ النسخ الاثنتين على نفس الجهاز:

```bash
chmod +x phantomroute
sudo cp phantomroute /usr/local/bin/        # على Termux: cp phantomroute $PREFIX/bin/
```

---

## 🚀 طريقة التشغيل

```bash
phantomroute                    # تشغيل بالإعدادات الافتراضية
phantomroute --interval 30      # تدوير كل 30 ثانية
phantomroute --no-mac           # تخطي تغيير MAC
phantomroute --no-killswitch    # تخطي Kill Switch
phantomroute --status           # عرض الحالة المحفوظة
phantomroute --panic            # استعادة النظام بعد انهيار
```

> ⚠️ **مهم:** الأداة **لا تحوّل كل حركة النظام تلقائياً إلى Tor**. عند تفعيل الـ Kill Switch يُحجب أي اتصال لا يمر عبر Tor، لذلك يجب ضبط برامجك على **SOCKS5 ‏`127.0.0.1:9050`** (المتصفح مثلاً) أو تشغيلها عبر `torsocks` / `proxychains`، وإلا لن يعمل الإنترنت لها أثناء التشغيل.
>
> الاتصالات القائمة التي لا تمر عبر Tor (تحميلات، SSH…) **تنقطع عمداً** عند التفعيل حتى لا تسرّب عنوانك الحقيقي. استخدم `--no-killswitch` إن لم ترد ذلك.

اضغط **Ctrl + C** في أي وقت لإيقاف الأداة (أو أغلق الطرفية)، وستقوم تلقائياً بـ:

1. إزالة قاعدة الـ Kill Switch الخاصة بها فقط.
2. استعادة `resolv.conf` وخدمة `systemd-resolved`.
3. إيقاف Tor إذا لم يكن يعمل قبل التشغيل، واستعادة `torrc`.
4. استعادة MAC Address و Hostname الأصليين.
5. اختبار الاتصال والتأكد من أن الإنترنت يعمل.

### الخيارات

| الخيار | الوصف |
|---|---|
| `--interval N` | عدد الثواني بين كل تدوير (Kali: 60، Termux: 90) |
| `--no-mac` | عدم تغيير MAC (Kali) |
| `--no-killswitch` | عدم تفعيل iptables (Kali) |
| `--status` | طباعة محتوى `state.json` |
| `--panic` | تنفيذ الاستعادة الطارئة |

---

## 🆘 استعادة النظام بعد انهيار

إذا انقطع الإنترنت بعد إغلاق الأداة بشكل غير طبيعي (إعادة تشغيل، انقطاع كهرباء…):

```bash
sudo phantomroute --panic
```

وإذا لم ينفع، نفّذ يدوياً:

```bash
sudo iptables  -D OUTPUT -j PHANTOMR_OUT  && sudo iptables  -F PHANTOMR_OUT  && sudo iptables  -X PHANTOMR_OUT
sudo ip6tables -D OUTPUT -j PHANTOMR_OUT6 && sudo ip6tables -F PHANTOMR_OUT6 && sudo ip6tables -X PHANTOMR_OUT6
sudo systemctl restart systemd-resolved
sudo systemctl restart NetworkManager
```

---

## 📂 ملفات تنشئها الأداة

| المسار | الغرض |
|---|---|
| `/var/lib/phantomroute/state.json` (Kali) | الحالة الأصلية للنظام قبل التشغيل |
| `~/.config/phantomroute/state.json` (Termux) | الحالة الأصلية قبل التشغيل |
| `~/phantomroute_report.txt` | تقرير الجلسة |

---

## ⚠️ حدود مهمة

- الأداة **لا تضمن إخفاء الهوية بالكامل**؛ بصمة المتصفح وتسجيل الدخول إلى حساباتك وسلوكك على الشبكة تكشفك بغض النظر عن Tor.
- تقييد بلد الخروج وتدويره بشكل متكرر قد يقلل من مناسبة Tor لبعض الاستخدامات؛ لا تعتمد عليها في سيناريوهات تهديد عالية.
- بعض المواقع تحظر عناوين Tor.
- تعديل `iptables` و `resolv.conf` و MAC يتطلب صلاحيات Root ويؤثر على الشبكة بالكامل أثناء التشغيل.

---

## 🧯 تنبيه وإخلاء مسؤولية

هذه الأداة مخصصة **للأغراض التعليمية واختبار الأمان الشخصي والخصوصية فقط**، وعلى أجهزة وشبكات تملكها أو لديك إذن صريح باختبارها.
المستخدم هو المسؤول الأول عن أي استخدام غير قانوني، والمطوّر غير مسؤول عن أي ضرر ناتج عن سوء الاستخدام.

---

## 📝 سجل التغييرات

**v1.1**
- إصلاح: الأداة كانت ترفض التشغيل للمرة الثانية بعد أول إيقاف نظيف.
- إصلاح: الـ Kill Switch كان يحجب Tor نفسه؛ أصبح يسمح لمستخدم Tor ولـ loopback فقط، ويغطي IPv6.
- أمان: منفذ التحكم في Tor صار محمياً بكلمة مرور عشوائية بدل الدخول المفتوح.
- تحسين: انتظار اكتمال اتصال Tor فعلياً بدل `sleep`، وتبديل البلد دون إعادة تشغيل.
- تحسين: إعادة Tor و`torrc` لحالتهما الأصلية عند الخروج، والتعامل مع إغلاق الطرفية (SIGHUP).
- تحسين: تقرير الجلسة يُكتب فعلاً، وحالة الاستعادة تُحفظ في مسار ثابت `/var/lib/phantomroute`.
- التثبيت صار على مستوى النظام (`/usr/local`) كي لا يُنفَّذ كود بصلاحيات root من مجلد قابل للتعديل.

## 🤝 المساهمة

الإصدارات والاقتراحات عبر **Issues** و **Pull Requests** مرحّب بها.

## 👤 المطوّر

**Black-ghost7** — [GitHub](https://github.com/Black-ghost7)

</div>
