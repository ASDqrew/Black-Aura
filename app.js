const header = document.querySelector('[data-header]');
const menuButton = document.querySelector('[data-menu-button]');
const menu = document.querySelector('[data-menu]');
const bookingForm = document.querySelector('[data-booking-form]');
const formResult = document.querySelector('[data-form-result]');

const closeMenu = () => {
  menu?.classList.remove('is-open');
  menuButton?.setAttribute('aria-expanded', 'false');
  document.body.classList.remove('menu-open');
};

menuButton?.addEventListener('click', () => {
  const shouldOpen = menuButton.getAttribute('aria-expanded') !== 'true';
  menu.classList.toggle('is-open', shouldOpen);
  menuButton.setAttribute('aria-expanded', String(shouldOpen));
  document.body.classList.toggle('menu-open', shouldOpen);
});

menu?.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeMenu));

window.addEventListener(
  'scroll',
  () => header?.classList.toggle('is-scrolled', window.scrollY > 20),
  { passive: true },
);

const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.13 },
);

document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));

bookingForm?.addEventListener('submit', (event) => {
  event.preventDefault();
  formResult.hidden = false;
  formResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});

document.querySelectorAll('[data-year]').forEach((node) => {
  node.textContent = new Date().getFullYear();
});
