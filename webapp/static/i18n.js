// DQ7 Viewer 共通i18n基盤。全ページでapp/save/等のページ専用scriptより前に読み込む。
// モジュール形式(model.js)からも使えるよう window.DQ7I18N に公開する。
(function () {
  'use strict';

  var STORAGE_KEY = 'dq7viewer_lang';

  // namespace付きキー。ページ専用の辞書エントリは各ページ担当者が追記する。
  var DICT = {
    ja: {
      'nav.script': 'スクリプト',
      'nav.fpt': 'FPT',
      'nav.floor': 'フロア',
      'nav.encount': 'エンカウント',
      'nav.item': 'アイテム',
      'nav.action': '特技・呪文',
      'nav.character': 'キャラ',
      'nav.model': 'モデル',
      'nav.map3d': 'マップ3D',
      'nav.images': '画像',
      'nav.save': 'セーブ',
      'nav.keifa_probe': 'キーファ調査',
      'nav.jidx': 'jidx',

      'common.loading': '読み込み中...',
      'common.error': 'エラー',
      'common.none': '(なし)',
      'common.unknown': '不明',
      'common.langToggle': 'EN',
    },
    en: {
      'nav.script': 'Script',
      'nav.fpt': 'FPT',
      'nav.floor': 'Floor',
      'nav.encount': 'Encounter',
      'nav.item': 'Item',
      'nav.action': 'Skills/Spells',
      'nav.character': 'Character',
      'nav.model': 'Model',
      'nav.map3d': 'Map 3D',
      'nav.images': 'Images',
      'nav.save': 'Save',
      'nav.keifa_probe': 'Kiefer Probe',
      'nav.jidx': 'jidx',

      'common.loading': 'Loading...',
      'common.error': 'Error',
      'common.none': '(none)',
      'common.unknown': 'Unknown',
      'common.langToggle': 'JA',
    },
  };

  function getLang() {
    try {
      var v = window.localStorage.getItem(STORAGE_KEY);
      return v === 'en' ? 'en' : 'ja';
    } catch (e) {
      return 'ja';
    }
  }

  function setLang(lang) {
    lang = lang === 'en' ? 'en' : 'ja';
    try { window.localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* ignore */ }
    applyI18n(document);
    window.dispatchEvent(new CustomEvent('dq7lang:change', { detail: { lang: lang } }));
    var btn = document.getElementById('langToggleBtn');
    if (btn) btn.textContent = t('common.langToggle');
  }

  function t(key, fallback) {
    var lang = getLang();
    var table = DICT[lang] || DICT.ja;
    if (Object.prototype.hasOwnProperty.call(table, key)) return table[key];
    if (Object.prototype.hasOwnProperty.call(DICT.ja, key)) return DICT.ja[key];
    return fallback !== undefined ? fallback : key;
  }

  // ページ専用jsがDICTへキーを追加するための窓口。
  function extend(entries) {
    if (entries.ja) Object.assign(DICT.ja, entries.ja);
    if (entries.en) Object.assign(DICT.en, entries.en);
  }

  function applyI18n(root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    root.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      el.innerHTML = t(el.getAttribute('data-i18n-html'));
    });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
    });
    root.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
    });
  }

  function initLangToggle() {
    var header = document.querySelector('header');
    if (!header || document.getElementById('langToggleBtn')) return;
    var btn = document.createElement('button');
    btn.id = 'langToggleBtn';
    btn.className = 'mode-btn';
    btn.type = 'button';
    btn.textContent = t('common.langToggle');
    btn.addEventListener('click', function () {
      setLang(getLang() === 'en' ? 'ja' : 'en');
    });
    header.appendChild(btn);
  }

  function init() {
    applyI18n(document);
    initLangToggle();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.DQ7I18N = {
    t: t,
    getLang: getLang,
    setLang: setLang,
    applyI18n: applyI18n,
    extend: extend,
  };
})();
