#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import json
import sqlite3
import asyncio
import random
import threading
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ============================================================
# 1. الإعدادات الأساسية (غيّرها حسب بياناتك)
# ============================================================

# توكن البوت من @BotFather
BOT_TOKEN = "8710044999:AAGsGCewdnb4sqrwE8dkRfQErKvLklpwP8M"

# معرفات القنوات (ضع معرف القناة بدون @)
TELEGRAM_CHANNEL_ID = "https://t.me/thaish12"    # مثال: "@giftcode_ar"
YOUTUBE_CHANNEL_URL = "https://youtube.com/@tahish159?si=zqr7b5ZPH-M6vvai"  # رابط قناتك

# حساب المالك (لمنح صلاحيات الإدارة)
OWNER_ID = 6366853738  # ضع معرف التلغرام الخاص بك (أرقام فقط)

# مسار قاعدة البيانات
DB_PATH = "users.db"

# ============================================================
# 2. قاعدة البيانات (SQLite)
# ============================================================

def init_db():
    """إنشاء جداول قاعدة البيانات إذا لم تكن موجودة"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # جدول المستخدمين
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            referral_code TEXT,
            start_number INTEGER DEFAULT 4054956,
            current_number INTEGER DEFAULT 4054956,
            total_gold INTEGER DEFAULT 0,
            successful_refs INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subscribed_telegram INTEGER DEFAULT 0,
            subscribed_youtube INTEGER DEFAULT 0,
            trial_expiry TIMESTAMP DEFAULT NULL
        )
    ''')
    
    # جدول الإحالات الناجحة (لتجنب التكرار)
    c.execute('''
        CREATE TABLE IF NOT EXISTS successful_refs (
            user_id INTEGER,
            target_id TEXT,
            PRIMARY KEY (user_id, target_id)
        )
    ''')
    
    # جدول البروكسيات (يديرها المالك)
    c.execute('''
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proxy TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def get_user(user_id):
    """جلب بيانات مستخدم معين"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username, full_name, referral_code):
    """إنشاء مستخدم جديد"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, full_name, referral_code, start_number, current_number)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, full_name, referral_code, 4054956, 4054956))
    conn.commit()
    conn.close()

def update_user_start_number(user_id, new_number):
    """تحديث رقم البداية لمستخدم"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET start_number = ?, current_number = ? WHERE user_id = ?', 
              (new_number, new_number, user_id))
    conn.commit()
    conn.close()

def get_current_number(user_id):
    """جلب الرقم الحالي لمستخدم معين"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT current_number FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 4054956

def increment_current_number(user_id):
    """زيادة الرقم الحالي للمستخدم (مرة واحدة)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET current_number = current_number + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def save_successful_ref(user_id, target_id):
    """تسجيل إحالة ناجحة لتجنب التكرار"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO successful_refs (user_id, target_id) VALUES (?, ?)', (user_id, target_id))
    conn.commit()
    conn.close()

def is_ref_already_done(user_id, target_id):
    """التحقق إذا كانت الإحالة قد تمت مسبقاً"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT 1 FROM successful_refs WHERE user_id = ? AND target_id = ?', (user_id, target_id))
    result = c.fetchone()
    conn.close()
    return result is not None

def get_trial_expiry(user_id):
    """جلب تاريخ انتهاء الفترة التجريبية"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT trial_expiry FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def set_trial_expiry(user_id, expiry_date):
    """تعيين تاريخ انتهاء الفترة التجريبية"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET trial_expiry = ? WHERE user_id = ?', (expiry_date, user_id))
    conn.commit()
    conn.close()

def update_user_stats(user_id, gold, success_count):
    """تحديث إحصائيات المستخدم"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET total_gold = total_gold + ?, successful_refs = successful_refs + ? WHERE user_id = ?', 
              (gold, success_count, user_id))
    conn.commit()
    conn.close()

def get_proxies():
    """جلب قائمة البروكسيات النشطة (من جدول المالك)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT proxy FROM proxies WHERE status = "active"')
    proxies = [row[0] for row in c.fetchall()]
    conn.close()
    return proxies

def add_proxy(proxy):
    """إضافة بروكسي جديد (للمالك فقط)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO proxies (proxy) VALUES (?)', (proxy,))
    conn.commit()
    conn.close()

def remove_proxy(proxy):
    """حذف بروكسي (للمالك فقط)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM proxies WHERE proxy = ?', (proxy,))
    conn.commit()
    conn.close()

# ============================================================
# 3. دوال التحقق من الاشتراك
# ============================================================

async def check_telegram_subscription(user_id, bot):
    """التحقق من اشتراك المستخدم في قناة التلغرام"""
    try:
        member = await bot.get_chat_member(chat_id=TELEGRAM_CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def check_youtube_subscription(user_id):
    """التحقق من اشتراك المستخدم في قناة اليوتيوب (محاكاة)"""
    # نظراً لأن يوتيوب لا يوفر API للتحقق من الاشتراك بسهولة،
    # نطلب من المستخدم تأكيد اشتراكه يدوياً عبر زر
    # وسنحفظ حالته في قاعدة البيانات
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT subscribed_youtube FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] == 1 if result else False

async def confirm_youtube_subscription(user_id):
    """تأكيد اشتراك اليوتيوب (بعد ضغط المستخدم على زر التأكيد)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET subscribed_youtube = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# ============================================================
# 4. دوال الإحالات الأساسية (معدلة من الكود الأصلي)
# ============================================================

def test_proxy(proxy, referral_code="4094894"):
    """اختبار البروكسي باستخدام رقم معروف"""
    url = "https://giftcode.betelgeuse.app/api/referrer"
    params = {
        "referred_user_id": "4094894",
        "ref_code": referral_code
    }
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJndGF2NTEwMzFAZ21haWwuY29tIn0.LR0lbOdO6Qq5d_4X0jKUC6mx18PP1-w2ChvBXQTETw0",
        "User-Agent": "okhttp/5.3.2"
    }
    proxies = {"http": proxy, "https": proxy}
    try:
        response = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=8)
        if response.status_code in [200, 429, 403, 404]:
            return True
        return False
    except:
        return False

def send_referral(target_user_id, proxy, referral_code="4094894"):
    """إرسال طلب إحالة لرقم معين عبر بروكسي"""
    url = "https://giftcode.betelgeuse.app/api/referrer"
    params = {
        "referred_user_id": target_user_id,
        "ref_code": referral_code
    }
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJndGF2NTEwMzFAZ21haWwuY29tIn0.LR0lbOdO6Qq5d_4X0jKUC6mx18PP1-w2ChvBXQTETw0",
        "User-Agent": "okhttp/5.3.2"
    }
    proxies = {"http": proxy, "https": proxy}
    try:
        response = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return {"success": True, "gold": data.get("referred_gold", 0)}
            elif "Zaten referanslı" in data.get("reason", ""):
                return {"success": False, "reason": "already_referred"}
            elif "Geçersiz kullanıcı" in data.get("reason", ""):
                return {"success": False, "reason": "invalid_user"}
            else:
                return {"success": False, "reason": "unknown"}
        elif response.status_code == 429:
            return {"success": False, "reason": "rate_limited"}
        else:
            return {"success": False, "reason": f"http_{response.status_code}"}
    except Exception as e:
        return {"success": False, "reason": "proxy_dead", "error": str(e)}

# ============================================================
# 5. دوال البوت الرئيسية
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسالة الترحيب والتحقق من الاشتراك"""
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    # إنشاء المستخدم إذا لم يكن موجوداً
    user_data = get_user(user_id)
    if not user_data:
        # توليد كود إحالة فريد (مختصر)
        ref_code = f"REF{user_id % 1000000:06d}"
        create_user(user_id, username, user.first_name, ref_code)
        set_trial_expiry(user_id, (datetime.now() + timedelta(hours=24)).isoformat())
    
    # التحقق من الاشتراك في التلغرام
    bot = context.bot
    is_subscribed_telegram = await check_telegram_subscription(user_id, bot)
    
    # إذا لم يكن مشتركاً، نطلب منه الاشتراك
    if not is_subscribed_telegram:
        keyboard = [
            [InlineKeyboardButton("📢 اشترك في قناة التلغرام", url=f"https://t.me/{TELEGRAM_CHANNEL_ID.replace('@', '')}")],
            [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_telegram")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"👋 أهلاً بك {username}!\n\n"
            f"🔹 **للبدء في استخدام البوت، اشترك أولاً في قناتنا على التلغرام:**\n"
            f"📢 {TELEGRAM_CHANNEL_URL}\n\n"
            f"بعد الاشتراك، اضغط على زر 'تحقق من الاشتراك'.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # التحقق من اشتراك اليوتيوب
    is_subscribed_youtube = await check_youtube_subscription(user_id)
    if not is_subscribed_youtube:
        keyboard = [
            [InlineKeyboardButton("🎬 اشترك في قناة اليوتيوب", url=YOUTUBE_CHANNEL_URL)],
            [InlineKeyboardButton("✅ تم الاشتراك (تأكيد)", callback_data="confirm_youtube")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"🎉 مرحباً بك {username}!\n\n"
            f"أنت الآن مشترك في قناة التلغرام ✅\n\n"
            f"🔹 **الخطوة التالية:** اشترك في قناتنا على **يوتيوب** أيضاً:\n"
            f"🎬 {YOUTUBE_CHANNEL_URL}\n\n"
            f"بعد الاشتراك، اضغط على زر 'تم الاشتراك'.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # إذا كان مشتركاً في كل شيء، نعرض له القائمة الرئيسية
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القائمة الرئيسية للمستخدم"""
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data:
        await start(update, context)
        return
    
    # التحقق من الفترة التجريبية
    expiry = get_trial_expiry(user_id)
    if expiry:
        expiry_date = datetime.fromisoformat(expiry)
        if datetime.now() > expiry_date:
            # انتهت الفترة التجريبية
            await update.message.reply_text(
                "⏰ **انتهت الفترة التجريبية المجانية (24 ساعة)!**\n\n"
                "للاستمرار في استخدام البوت، يرجى التواصل مع المالك لتجديد الاشتراك.\n"
                "📩 @YourOwnerUsername",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    # عرض القائمة
    current_num = get_current_number(user_id)
    keyboard = [
        [InlineKeyboardButton("🎯 عرض رمز الإحالة", callback_data="show_ref")],
        [InlineKeyboardButton("🚀 بدء الإحالات (تشغيل البوت)", callback_data="start_ref")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="my_stats")],
        [InlineKeyboardButton("⚙️ تغيير رقم البداية", callback_data="change_start")],
    ]
    # إذا كان المالك، نضيف زر الإدارة
    if user_id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("🔧 لوحة التحكم (المالك)", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🏠 **القائمة الرئيسية**\n\n"
        f"👤 المستخدم: {user_data[2] or user_data[1]}\n"
        f"📌 آخر رقم مستخدم: {current_num}\n"
        f"💰 إجمالي الذهب: {user_data[6] or 0}\n"
        f"✅ الإحالات الناجحة: {user_data[7] or 0}\n\n"
        f"اختر أحد الخيارات أدناه:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_referral_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض رمز الإحالة الخاص بالمستخدم"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.edit_message_text("❌ حدث خطأ، يرجى إعادة تشغيل البوت بـ /start")
        return
    
    ref_code = user_data[3]  # referral_code
    await query.edit_message_text(
        f"🔑 **رمز الإحالة الخاص بك:**\n\n"
        f"`{ref_code}`\n\n"
        f"شارك هذا الرمز مع أصدقائك ليحصلوا على مكافآت! 🎁\n\n"
        f"📌 **ملاحظة:** عند إدخال رمزك، سيبدأ البوت في إحالة أشخاص لك.",
        parse_mode=ParseMode.MARKDOWN
    )

async def start_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية الإحالات (تشغيل البوت)"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.edit_message_text("❌ حدث خطأ، يرجى إعادة تشغيل البوت بـ /start")
        return
    
    # التحقق من الفترة التجريبية
    expiry = get_trial_expiry(user_id)
    if expiry:
        expiry_date = datetime.fromisoformat(expiry)
        if datetime.now() > expiry_date:
            await query.edit_message_text(
                "⏰ **انتهت الفترة التجريبية!**\n"
                "تواصل مع المالك لتجديد الاشتراك.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    ref_code = user_data[3]  # رمز الإحالة الخاص بالمستخدم
    
    # جلب البروكسيات
    proxies = get_proxies()
    if not proxies:
        await query.edit_message_text("⚠️ لا يوجد بروكسيات متاحة حالياً. يرجى التواصل مع المالك.")
        return
    
    # إرسال رسالة تشغيل
    await query.edit_message_text(
        f"🚀 **جاري تشغيل البوت للإحالات...**\n\n"
        f"🔑 رمز الإحالة: `{ref_code}`\n"
        f"📋 عدد البروكسيات: {len(proxies)}\n"
        f"⏳ سيتم إرسال النتائج لحظة بلحظة...\n\n"
        f"🛑 اضغط /stop لإيقاف العملية.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # تشغيل عملية الإحالات في خلفية (نستخدم threading)
    threading.Thread(target=run_referrals, args=(user_id, ref_code, proxies, context.bot)).start()

def run_referrals(user_id, ref_code, proxies, bot):
    """تشغيل الإحالات في خلفية (هذه الدالة تعمل في thread منفصل)"""
    current_num = get_current_number(user_id)
    stats = {"success": 0, "already": 0, "invalid": 0, "dead": 0, "failed": 0, "gold": 0}
    
    # دوران على البروكسيات
    for proxy in proxies:
        # اختبار البروكسي
        if not test_proxy(proxy, ref_code):
            stats["failed"] += 1
            continue
        
        # محاولة الإحالة
        target = str(current_num)
        current_num += 1
        increment_current_number(user_id)  # حفظ الرقم الجديد في قاعدة البيانات
        
        # التحقق من عدم تكرار الإحالة
        if is_ref_already_done(user_id, target):
            stats["already"] += 1
            continue
        
        result = send_referral(target, proxy, ref_code)
        
        if result.get("success"):
            stats["success"] += 1
            gold = result.get("gold", 0)
            stats["gold"] += gold
            save_successful_ref(user_id, target)
            update_user_stats(user_id, gold, 1)
            # إرسال إشعار للمستخدم
            asyncio.run(send_notification(bot, user_id, target, gold))
        elif result.get("reason") == "already_referred":
            stats["already"] += 1
        elif result.get("reason") == "invalid_user":
            stats["invalid"] += 1
            # الرقم غير صالح، ننتقل للتالي
        elif result.get("reason") == "rate_limited":
            stats["failed"] += 1
        elif result.get("reason") == "proxy_dead":
            stats["dead"] += 1
        else:
            stats["failed"] += 1
        
        # تأخير بسيط بين المحاولات
        time.sleep(random.uniform(0.5, 1.0))
    
    # بعد الانتهاء من جميع البروكسيات
    final_message = (
        f"✅ **تم الانتهاء من تشغيل البوت!**\n\n"
        f"📊 **النتيجة النهائية:**\n"
        f"✅ إحالات ناجحة: {stats['success']}\n"
        f"💰 إجمالي الذهب المكتسب: {stats['gold']} GP\n"
        f"⚠️ محال مسبقاً: {stats['already']}\n"
        f"❌ مستخدمين غير صالحين: {stats['invalid']}\n"
        f"⏳ بروكسيات ميتة: {stats['dead']}\n"
        f"❌ إخفاقات أخرى: {stats['failed']}\n\n"
        f"📌 آخر رقم تم استخدامه: {current_num - 1}\n"
        f"🔢 رقم البداية التالي: {current_num}\n\n"
        f"للبدء من جديد، عدّل رقم البداية في القائمة الرئيسية."
    )
    asyncio.run(send_notification(bot, user_id, None, None, final_message))

async def send_notification(bot, user_id, target=None, gold=None, final_msg=None):
    """إرسال إشعار للمستخدم (في الخلفية)"""
    if final_msg:
        await bot.send_message(chat_id=user_id, text=final_msg, parse_mode=ParseMode.MARKDOWN)
    else:
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ إحالة ناجحة! المستخدم: `{target}` ، +{gold} GP",
            parse_mode=ParseMode.MARKDOWN
        )

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات المستخدم"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.edit_message_text("❌ حدث خطأ، يرجى إعادة تشغيل البوت بـ /start")
        return
    
    current_num = get_current_number(user_id)
    expiry = get_trial_expiry(user_id)
    expiry_text = "⏰ **انتهت**" if expiry and datetime.now() > datetime.fromisoformat(expiry) else "✅ **نشطة**"
    
    await query.edit_message_text(
        f"📊 **إحصائياتك الشخصية:**\n\n"
        f"👤 المستخدم: {user_data[2] or user_data[1]}\n"
        f"🔑 رمز الإحالة: `{user_data[3]}`\n"
        f"💰 إجمالي الذهب: {user_data[6] or 0} GP\n"
        f"✅ الإحالات الناجحة: {user_data[7] or 0}\n"
        f"🔢 رقم البداية الحالي: {user_data[4] or 4054956}\n"
        f"📌 آخر رقم مستخدم: {current_num}\n"
        f"📅 الفترة التجريبية: {expiry_text}\n\n"
        f"📌 **ملاحظة:** إذا نفذت البروكسيات، سيتم إيقاف البوت تلقائياً.",
        parse_mode=ParseMode.MARKDOWN
    )

async def change_start_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغيير رقم البداية (يرسل رسالة يطلب فيها إدخال الرقم)"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data:
        await query.edit_message_text("❌ حدث خطأ، يرجى إعادة تشغيل البوت بـ /start")
        return
    
    current_start = user_data[4] or 4054956
    await query.edit_message_text(
        f"⚙️ **تغيير رقم البداية**\n\n"
        f"الرقم الحالي: `{current_start}`\n\n"
        f"📝 أرسل الرقم الجديد (أعداد صحيحة فقط):\n"
        f"(مثال: 4054956)\n\n"
        f"🛑 لإلغاء، اكتب /cancel",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['waiting_for_new_number'] = True

async def handle_new_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال الرقم الجديد من المستخدم"""
    if not context.user_data.get('waiting_for_new_number'):
        return
    
    user_id = update.effective_user.id
    try:
        new_number = int(update.message.text.strip())
        if new_number < 1000000:
            await update.message.reply_text("⚠️ الرقم صغير جداً، أدخل رقماً أكبر من 1,000,000.")
            return
        update_user_start_number(user_id, new_number)
        await update.message.reply_text(f"✅ تم تحديث رقم البداية إلى: `{new_number}`", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً فقط (مثل: 4054956)")
    
    context.user_data['waiting_for_new_number'] = False
    # العودة للقائمة الرئيسية
    await show_main_menu(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء العملية الحالية"""
    context.user_data.clear()
    await update.message.reply_text("🚫 تم الإلغاء.")
    await show_main_menu(update, context)

# ============================================================
# 6. لوحة تحكم المالك
# ============================================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة تحكم المالك"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id != OWNER_ID:
        await query.edit_message_text("⛔ غير مصرح لك بدخول هذه اللوحة.")
        return
    
    proxies = get_proxies()
    keyboard = [
        [InlineKeyboardButton("➕ إضافة بروكسي", callback_data="add_proxy")],
        [InlineKeyboardButton("➖ حذف بروكسي", callback_data="remove_proxy")],
        [InlineKeyboardButton("📋 عرض البروكسيات", callback_data="list_proxies")],
        [InlineKeyboardButton("📊 إحصائيات عامة", callback_data="global_stats")],
        [InlineKeyboardButton("📢 بث رسالة للجميع", callback_data="broadcast")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"🔧 **لوحة تحكم المالك**\n\n"
        f"📋 عدد البروكسيات النشطة: {len(proxies)}\n"
        f"👥 عدد المستخدمين: {get_total_users()}\n\n"
        f"اختر الإجراء المناسب:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

def get_total_users():
    """جلب عدد المستخدمين الكلي"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    count = c.fetchone()[0]
    conn.close()
    return count

async def add_proxy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طلب إدخال بروكسي جديد"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        await query.edit_message_text("⛔ غير مصرح.")
        return
    await query.edit_message_text(
        "📝 أرسل البروكسي الجديد (بالصيغة: `ip:port` أو `http://ip:port`):\n"
        "مثال: `103.148.62.1:8080`\n\n"
        "🛑 لإلغاء، اكتب /cancel",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['waiting_for_proxy'] = True

async def handle_new_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال بروكسي جديد من المالك"""
    if not context.user_data.get('waiting_for_proxy'):
        return
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ غير مصرح.")
        return
    
    proxy = update.message.text.strip()
    if not proxy.startswith("http://") and not proxy.startswith("https://"):
        proxy = f"http://{proxy}"
    add_proxy(proxy)
    await update.message.reply_text(f"✅ تم إضافة البروكسي: `{proxy}`", parse_mode=ParseMode.MARKDOWN)
    context.user_data['waiting_for_proxy'] = False
    await admin_panel(update, context)

async def list_proxies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة البروكسيات"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        await query.edit_message_text("⛔ غير مصرح.")
        return
    
    proxies = get_proxies()
    if not proxies:
        await query.edit_message_text("📋 لا يوجد بروكسيات حالياً.")
        return
    
    text = "📋 **قائمة البروكسيات النشطة:**\n\n"
    for i, p in enumerate(proxies, 1):
        text += f"{i}. `{p}`\n"
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رسالة لجميع المستخدمين"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        await query.edit_message_text("⛔ غير مصرح.")
        return
    await query.edit_message_text(
        "📢 أرسل الرسالة التي تريد بثها لجميع المستخدمين:\n\n"
        "🛑 لإلغاء، اكتب /cancel",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['waiting_for_broadcast'] = True

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسالة البث"""
    if not context.user_data.get('waiting_for_broadcast'):
        return
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ غير مصرح.")
        return
    
    message = update.message.text
    # جلب جميع المستخدمين
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id FROM users')
    users = c.fetchall()
    conn.close()
    
    sent = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message, parse_mode=ParseMode.MARKDOWN)
            sent += 1
            await asyncio.sleep(0.1)  # تجنب الحظر
        except:
            pass
    
    await update.message.reply_text(f"✅ تم إرسال الرسالة إلى {sent} مستخدم.")
    context.user_data['waiting_for_broadcast'] = False
    await show_main_menu(update, context)

# ============================================================
# 7. تشغيل البوت
# ============================================================

def main():
    # تهيئة قاعدة البيانات
    init_db()
    
    # إنشاء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()
    
    # أوامر البوت
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("stop", start))  # للعودة للقائمة
    
    # معالجة الأزرار (CallbackQuery)
    application.add_handler(CallbackQueryHandler(show_referral_code, pattern="^show_ref$"))
    application.add_handler(CallbackQueryHandler(start_referral, pattern="^start_ref$"))
    application.add_handler(CallbackQueryHandler(my_stats, pattern="^my_stats$"))
    application.add_handler(CallbackQueryHandler(change_start_number, pattern="^change_start$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    application.add_handler(CallbackQueryHandler(add_proxy_handler, pattern="^add_proxy$"))
    application.add_handler(CallbackQueryHandler(list_proxies, pattern="^list_proxies$"))
    application.add_handler(CallbackQueryHandler(broadcast, pattern="^broadcast$"))
    
    # معالجة الرسائل النصية
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_number))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_proxy))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast))
    
    # زر العودة للقائمة الرئيسية
    async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await show_main_menu(update, context)
    
    # بدء البوت
    print("🚀 البوت شغال...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
