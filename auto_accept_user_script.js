// ==UserScript==
// @name         Antigravity Auto-Accept Bot
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Otomatik onay butonlarına tıklar (arka planda çalışır)
// @author       Antigravity
// @match        *://*/*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    // Arayacağımız buton metinleri (küçük harf olarak yazın)
    const TARGET_TEXTS = ['run', 'accept', 'approve', 'onayla', 'çalıştır'];

    function checkAndClick() {
        // Sayfadaki tüm butonları ve tıklanabilir elementleri bul
        const elements = document.querySelectorAll('button, a, input[type="button"], input[type="submit"], div[role="button"]');

        for (const el of elements) {
            const text = el.textContent.trim().toLowerCase() || el.value?.trim().toLowerCase() || '';
            
            // Eğer buton metni hedef kelimelerimizden birini içeriyorsa ve görünür/aktif ise tıkla
            if (TARGET_TEXTS.some(target => text.includes(target))) {
                // Elementin gizli veya devre dışı (disabled) olmadığını kontrol et
                if (!el.disabled && el.offsetParent !== null) {
                    console.log(`[Auto-Accept] Buton bulundu ve tıklandı: "${text}"`);
                    el.click();
                    break; // Her döngüde tek bir tıklama yapıp çıkalım
                }
            }
        }
    }

    // Her 1 saniyede bir sayfayı kontrol et (1000 ms = 1 saniye)
    setInterval(checkAndClick, 1000);
})();
