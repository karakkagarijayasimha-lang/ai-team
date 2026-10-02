document.addEventListener('DOMContentLoaded', () => {
    // ============================
    // Navigation Bar & Mobile Menu
    // ============================
    const hamburger = document.querySelector('.hamburger');
    const navLinks = document.querySelector('.nav-links');
    const navLinksItems = document.querySelectorAll('.nav-links a');

    // Toggle mobile menu on hamburger click
    hamburger.addEventListener('click', () => {
        const isExpanded = hamburger.getAttribute('aria-expanded') === 'true';
        hamburger.setAttribute('aria-expanded', isExpanded ? 'false' : 'true');
        navLinks.classList.toggle('active');
    });

    // Close mobile menu when a navigation link is clicked
    navLinksItems.forEach(link => {
        link.addEventListener('click', () => {
            hamburger.setAttribute('aria-expanded', 'false');
            navLinks.classList.remove('active');
        });
    });

    // Close mobile menu when clicking outside the menu or hamburger
    document.addEventListener('click', (e) => {
        if (!hamburger.contains(e.target) && !navLinks.contains(e.target)) {
            hamburger.setAttribute('aria-expanded', 'false');
            navLinks.classList.remove('active');
        }
    });

    // ============================
    // Smooth Scrolling for Anchors
    // ============================
    // Select all anchor links that start with '#'
    const anchorLinks = document.querySelectorAll('a[href^="#"]');
    anchorLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            // Ignore empty href (e.g., href="#")
            if (targetId === '#') return;
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                e.preventDefault();
                // Smooth scroll to the target element
                targetElement.scrollIntoView({
                    behavior: 'smooth'
                });
            }
        });
    });

    // ============================
    // Contact Form Validation
    // ============================
    const contactForm = document.getElementById('contact-form');
    const nameInput = document.getElementById('name');
    const emailInput = document.getElementById('email');
    const messageInput = document.getElementById('message');
    
    const nameError = document.getElementById('name-error');
    const emailError = document.getElementById('email-error');
    const messageError = document.getElementById('message-error');
    const formSuccess = document.getElementById('form-success');

    // Simple email regex validation
    function validateEmail(email) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(String(email).toLowerCase());
    }

    // Handle form submission
    contactForm.addEventListener('submit', (e) => {
        e.preventDefault(); // Prevent default form submission
        let isValid = true;

        // Reset previous error messages and success banner
        nameError.textContent = '';
        emailError.textContent = '';
        messageError.textContent = '';
        formSuccess.style.display = 'none';

        // Validate Name: required
        if (!nameInput.value.trim()) {
            nameError.textContent = 'Name is required.';
            isValid = false;
        }

        // Validate Email: required and format
        if (!emailInput.value.trim()) {
            emailError.textContent = 'Email is required.';
            isValid = false;
        } else if (!validateEmail(emailInput.value.trim())) {
            emailError.textContent = 'Please enter a valid email address.';
            isValid = false;
        }

        // Validate Message: required
        if (!messageInput.value.trim()) {
            messageError.textContent = 'Message is required.';
            isValid = false;
        }

        // If all valid, show success message and reset form
        if (isValid) {
            formSuccess.style.display = 'block';
            contactForm.reset();

            // Hide success message after 5 seconds
            setTimeout(() => {
                formSuccess.style.display = 'none';
            }, 5000);
        }
    });

    console.log('Portfolio script loaded successfully.');
});