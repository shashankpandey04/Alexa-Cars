/**
 * Mobile responsive enhancements for the admin dashboard
 */

// Initialize mobile navigation
function initMobileNav() {
  // Add toggle button if it doesn't exist
  if (!document.querySelector('.nav-toggle')) {
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'nav-toggle';
    toggleBtn.innerHTML = '<i class="fas fa-bars"></i>';
    toggleBtn.setAttribute('aria-label', 'Toggle Navigation');
    document.body.appendChild(toggleBtn);
    
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    document.body.appendChild(overlay);
    
    toggleBtn.addEventListener('click', toggleSidebar);
    overlay.addEventListener('click', toggleSidebar);
  }
}

// Toggle sidebar visibility
function toggleSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.querySelector('.sidebar-overlay');
  
  sidebar.classList.toggle('open');
  overlay.classList.toggle('open');
  document.body.classList.toggle('sidebar-open');
}

// Add swipe hint for tables
function addTableScrollHints() {
  const tables = document.querySelectorAll('.table-container');
  if (tables.length > 0 && window.innerWidth < 768) {
    tables.forEach(container => {
      // Only add hint if it doesn't already exist
      if (!container.previousElementSibling || !container.previousElementSibling.classList.contains('table-scroll-hint')) {
        const hint = document.createElement('div');
        hint.className = 'table-scroll-hint';
        hint.innerHTML = '<i class="fas fa-arrows-left-right"></i> Swipe to view more';
        container.parentNode.insertBefore(hint, container);
        
        // Remove hint after user has scrolled the table
        container.addEventListener('scroll', function() {
          const hint = this.previousElementSibling;
          if (hint && hint.classList.contains('table-scroll-hint')) {
            hint.style.opacity = '0';
            setTimeout(() => {
              hint.remove();
            }, 300);
          }
        }, { once: true });
      }
    });
  }
}

// Make form controls more touch-friendly
function enhanceFormControls() {
  const formControls = document.querySelectorAll('.form-control');
  formControls.forEach(control => {
    control.classList.add('touch-friendly');
  });
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  // Execute only in mobile view
  if (window.innerWidth <= 768) {
    initMobileNav();
    addTableScrollHints();
    enhanceFormControls();
  }
  
  // Handle window resize
  window.addEventListener('resize', function() {
    if (window.innerWidth <= 768) {
      initMobileNav();
      addTableScrollHints();
    } else {
      // Reset sidebar state if screen size changes to desktop
      document.body.classList.remove('sidebar-open');
      const sidebar = document.querySelector('.sidebar');
      const overlay = document.querySelector('.sidebar-overlay');
      
      if (sidebar) sidebar.classList.remove('open');
      if (overlay) overlay.classList.remove('open');
    }
  });
});
