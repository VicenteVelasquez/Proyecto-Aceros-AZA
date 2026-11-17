document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.barra-dinamica').forEach(function(bar) {
    const ancho = bar.getAttribute('data-width');
    if (ancho) {
      bar.style.width = ancho + '%';
    }
  });
});