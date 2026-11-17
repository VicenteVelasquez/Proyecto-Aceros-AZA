// static/js/operador_recetas.js
document.addEventListener('DOMContentLoaded', function() {
  const inputBuscar = document.getElementById('input-buscar');
  const tbodyTabla = document.querySelector('#tabla-recetas tbody');

  if (!inputBuscar || !tbodyTabla) return;

  // Búsqueda dinámica asíncrona mediante la API de Flask 
  inputBuscar.addEventListener('input', async function() {
    const query = this.value.trim();

    try {
      const response = await fetch(`/api/recetas/buscar?q=${encodeURIComponent(query)}`);
      const data = await response.json();

      if (data.status === 'success') {
        actualizarTablaRecetas(data.recetas);
      } else {
        console.error("Error al buscar recetas:", data.mensaje);
      }
    } catch (error) {
      console.error("Error de red en la petición fetch:", error);
    }
  });

  // Función para redibujar la tabla de forma dinámica en el DOM
  function actualizarTablaRecetas(recetas) {
    tbodyTabla.innerHTML = '';

    if (recetas.length === 0) {
      tbodyTabla.innerHTML = `
        <tr>
          <td colspan="7" class="text-center py-3 text-muted">No se encontraron recetas registradas en PostgreSQL.</td>
        </tr>
      `;
      return;
    }

    recetas.forEach(receta => {
      const fila = document.createElement('tr');
      fila.innerHTML = `
        <td><strong>#${receta.id}</strong></td>
        <td><span class="badge bg-dark fs-6">${receta.codigo_receta}</span></td>
        <td class="fw-bold text-primary">${receta.angulo_nominal}°</td>
        <td class="text-danger fw-bold">${receta.tolerancia_min}°</td>
        <td class="text-success fw-bold">${receta.tolerancia_max}°</td>
        <td class="text-center"><span class="badge bg-success">Activa</span></td>
        <td class="text-center">
          <button class="btn btn-sm btn-outline-success btn-seleccionar" data-codigo="${receta.codigo_receta}" data-nominal="${receta.angulo_nominal}">
            <i class="fa-solid fa-check me-1"></i> Usar en Línea
          </button>
        </td>
      `;
      tbodyTabla.appendChild(fila);
    });

    // Reasignar eventos a los nuevos botones generados dinámicamente
    inicializarBotonesSeleccion();
  }

  // Función para manejar la selección de receta para la línea activa
  function inicializarBotonesSeleccion() {
    document.querySelectorAll('.btn-seleccionar').forEach(btn => {
      // Evitar duplicar eventos
      btn.removeEventListener('click', manejarSeleccion);
      btn.addEventListener('click', manejarSeleccion);
    });
  }

  function manejarSeleccion() {
    const codigo = this.getAttribute('data-codigo');
    const nominal = this.getAttribute('data-nominal');
    if (confirm(`¿Desea cargar la receta ${codigo} (Ángulo nominal: ${nominal}°) para el lote actual en planta?`)) {
      alert(`Receta ${codigo} cargada con éxito en el sistema M2M.`);
      window.location.href = "/operador/camara";
    }
  }

  // Inicializar eventos en la primera carga estática de la página
  inicializarBotonesSeleccion();
});