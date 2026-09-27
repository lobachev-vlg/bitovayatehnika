(function () {
    'use strict';

    document.body.classList.add('js-on');

    var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* ---------- 1. Появление блоков при скролле ---------- */
    var revealables = Array.prototype.slice.call(document.querySelectorAll('.reveal'));

    if (prefersReduced || !('IntersectionObserver' in window)) {
        revealables.forEach(function (el) { el.classList.add('is-in'); });
    } else {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('is-in');
                observer.unobserve(entry.target);
            });
        }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });

        revealables.forEach(function (el) { observer.observe(el); });

        /* страховка: если что-то осталось скрытым — показываем */
        window.setTimeout(function () {
            revealables.forEach(function (el) { el.classList.add('is-in'); });
        }, 2500);
    }

    /* ---------- 2. Липкая шапка + кнопка "наверх" ---------- */
    var header = document.querySelector('.site-header');
    var toTop = document.querySelector('[data-to-top]');

    function scrollY() {
        return window.pageYOffset ||
               (document.documentElement && document.documentElement.scrollTop) ||
               document.body.scrollTop || 0;
    }

    function onScroll() {
        var y = scrollY();
        if (header) header.classList.toggle('is-stuck', y > 8);
        if (toTop) toTop.classList.toggle('is-visible', y > 400);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    if (toTop) {
        toTop.addEventListener('click', function (e) {
            e.preventDefault();
            var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            if ('scrollBehavior' in document.documentElement.style) {
                window.scrollTo({ top: 0, left: 0, behavior: reduce ? 'auto' : 'smooth' });
            } else {
                window.scrollTo(0, 0);
            }
            if (history.replaceState) history.replaceState(null, '', location.pathname);
        });
    }

    /* ---------- 3. Мобильное меню ---------- */
    var burger = document.querySelector('[data-burger]');

    if (burger && header) {
        burger.addEventListener('click', function () {
            var open = header.classList.toggle('nav-open');
            burger.setAttribute('aria-expanded', String(open));
        });

        header.querySelectorAll('.nav a').forEach(function (link) {
            link.addEventListener('click', function () {
                header.classList.remove('nav-open');
                burger.setAttribute('aria-expanded', 'false');
            });
        });

        document.addEventListener('click', function (e) {
            if (!header.classList.contains('nav-open')) return;
            if (header.contains(e.target) || burger.contains(e.target)) return;
            header.classList.remove('nav-open');
            burger.setAttribute('aria-expanded', 'false');
        });
    }

    /* ---------- 4. Маска телефона ---------- */
    var phone = document.querySelector('[data-phone]');

    if (phone) {
        function formatPhone(value) {
            var digits = value.replace(/\D/g, '');
            if (digits.indexOf('8') === 0) digits = '7' + digits.slice(1);
            if (digits.indexOf('7') !== 0) digits = '7' + digits;
            digits = digits.slice(0, 11);

            var out = '+7';
            if (digits.length > 1) out += ' (' + digits.slice(1, 4);
            if (digits.length >= 5) out += ') ' + digits.slice(4, 7);
            if (digits.length >= 8) out += '-' + digits.slice(7, 9);
            if (digits.length >= 10) out += '-' + digits.slice(9, 11);
            return out;
        }

        phone.addEventListener('input', function () {
            phone.value = formatPhone(phone.value);
        });

        phone.addEventListener('focus', function () {
            if (!phone.value) phone.value = '+7 (';
        });

        phone.addEventListener('blur', function () {
            if (phone.value.replace(/\D/g, '').length <= 1) phone.value = '';
        });
    }

    /* ---------- 5. Состояние кнопки отправки ---------- */
    var form = document.querySelector('[data-request-form]');

    if (form) {
        form.addEventListener('submit', function (event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                form.reportValidity();
                return;
            }
            var button = form.querySelector('button[type="submit"]');
            if (button) {
                button.classList.add('is-loading');
                window.setTimeout(function () {
                    button.classList.remove('is-loading');
                    form.reset();
                }, 1200);
            }
        });
    }
})();
