document.addEventListener('DOMContentLoaded', () => {
  const mobileMenu = document.getElementById('mobile-menu');
  const navLinks = document.querySelector('.nav-links');
  const navbar = document.getElementById('navbar');
  const contactForm = document.getElementById('contact-form');
  const formFeedback = document.getElementById('form-feedback');

  // Mobile Menu Toggle
  mobileMenu.addEventListener('click', () => {
    navLinks.classList.toggle('active');
    mobileMenu.classList.toggle('active');
  });

  // Close mobile menu when a nav link is clicked
  document.querySelectorAll('.nav-links a').forEach(link => {
    link.addEventListener('click', () => {
      navLinks.classList.remove('active');
      mobileMenu.classList.remove('active');
    });
  });

  // Sticky Header State
  window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  });

  // Smooth Scrolling for Navigation Links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const targetId = this.getAttribute('href');
      const targetElement = document.querySelector(targetId);
      if (targetElement) {
        targetElement.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    });
  });

  // Form Validation
  contactForm.addEventListener('submit', function (e) {
    e.preventDefault();

    let isValid = true;
    const name = document.getElementById('name');
    const email = document.getElementById('email');
    const message = document.getElementById('message');

    // Clear previous errors
    document.querySelectorAll('.error-message').forEach(el => {
      el.textContent = '';
      el.style.display = 'none';
    });
    document.querySelectorAll('.form-group').forEach(el => {
      el.classList.remove('invalid');
    });
    formFeedback.textContent = '';

    // Validate Name
    if (name.value.trim() === '') {
      showError(name, 'Name is required.');
      isValid = false;
    }

    // Validate Email
    if (email.value.trim() === '') {
      showError(email, 'Email is required.');
      isValid = false;
    } else if (!isValidEmail(email.value.trim())) {
      showError(email, 'Please enter a valid email address.');
      isValid = false;
    }

    // Validate Message
    if (message.value.trim() === '') {
      showError(message, 'Message is required.');
      isValid = false;
    }

    if (isValid) {
      formFeedback.textContent = 'Message sent successfully!';
      formFeedback.style.color = '#22c55e';
      contactForm.reset();
      setTimeout(() => {
        formFeedback.textContent = '';
      }, 3000);
    }
  });

  function showError(input, message) {
    const formGroup = input.closest('.form-group');
    const errorEl = formGroup.querySelector('.error-message');
    formGroup.classList.add('invalid');
    errorEl.textContent = message;
    errorEl.style.display = 'block';
  }

  function isValidEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
  }
});