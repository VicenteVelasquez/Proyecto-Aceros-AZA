document.addEventListener("DOMContentLoaded", function () {
  // 1. Asignar turno automáticamente según hora local
  const horaActual = new Date().getHours();
  const inputTurnoAsignado = document.getElementById("turno-asignado");
  let turnoCalculado = "Turno Tarde";
  if (horaActual >= 7 && horaActual < 13) {
    turnoCalculado = "Turno Mañana";
  } else if (horaActual >= 13 && horaActual <= 23) {
    turnoCalculado = "Turno Tarde";
  } else {
    turnoCalculado = "Turno Noche";
  }
  if (inputTurnoAsignado) inputTurnoAsignado.value = turnoCalculado;

  // Referencias del DOM
  const selectReceta = document.getElementById("select-receta-activa");
  const metricNominal = document.getElementById("metric-nominal");
  const metricTolMin = document.getElementById("metric-tol-min");
  const metricTolMax = document.getElementById("metric-tol-max");
  const metricBatch = document.getElementById("metric-batch");
  const batchInput = document.getElementById("batch-actual-input");
  const hiddenAngulo = document.querySelector('input[name="angulo_medio"]');
  const formIniciarBatch = document.getElementById("form-iniciar-batch");

  // Crear input oculto para codigo_batch si no existe
  let hiddenCodigoBatch = document.getElementById("hidden-codigo-batch");
  if (!hiddenCodigoBatch && formIniciarBatch) {
    hiddenCodigoBatch = document.createElement("input");
    hiddenCodigoBatch.type = "hidden";
    hiddenCodigoBatch.name = "codigo_batch";
    hiddenCodigoBatch.id = "hidden-codigo-batch";
    formIniciarBatch.appendChild(hiddenCodigoBatch);
  }

  let tolMinActual = 44.5;
  let tolMaxActual = 45.5;
  let nominalActual = 45.0;
  let contadorBatch = 1;
  let ultimoRegistroId = null;

  // 2. Actualizar métricas reales al cambiar de receta
  function actualizarMetricasReceta() {
    if (!selectReceta || selectReceta.options.length === 0) return;
    const opt = selectReceta.options[selectReceta.selectedIndex];

    nominalActual = parseFloat(opt.getAttribute("data-nominal")) || 45.0;
    tolMinActual = parseFloat(opt.getAttribute("data-min")) || 44.5;
    tolMaxActual = parseFloat(opt.getAttribute("data-max")) || 45.5;
    const codigo = opt.getAttribute("data-codigo") || "AZA";

    if (metricNominal) metricNominal.textContent = nominalActual.toFixed(1) + " mm";
    if (metricTolMin) metricTolMin.textContent = tolMinActual.toFixed(1);
    if (metricTolMax) metricTolMax.textContent = tolMaxActual.toFixed(1);

    const nombreBatch = "BATCH-" + String(contadorBatch).padStart(2, "0");
    if (metricBatch) metricBatch.textContent = nombreBatch;
    if (batchInput) batchInput.value = "LOT-" + codigo + " / " + nombreBatch;
    if (hiddenCodigoBatch) hiddenCodigoBatch.value = nombreBatch;
  }

  if (selectReceta) {
    selectReceta.addEventListener("change", actualizarMetricasReceta);
    actualizarMetricasReceta();
  }

  // 3. Simulación de cámara 1660 FPS evaluando límites reales de la receta
  const measuredAngleEl = document.getElementById("measured-angle");
  const toleranceBadge = document.getElementById("tolerance-badge");
  const angleDeviation = document.getElementById("angle-deviation");
  const obsAngleEl = document.getElementById("observation-angle");

  function simularCapturaAltaVelocidad() {
    // Genera ángulo centrado en el nominal de la receta con margen para probar aprobado y desviado
    const rango = (tolMaxActual - tolMinActual) || 1.0;
    const variacion = (Math.random() - 0.45) * (rango * 1.4);
    const anguloSimulado = +(nominalActual + variacion).toFixed(1);

    if (measuredAngleEl) measuredAngleEl.textContent = anguloSimulado.toFixed(1) + "°";
    if (obsAngleEl) obsAngleEl.textContent = anguloSimulado.toFixed(1) + "°";
    if (hiddenAngulo) hiddenAngulo.value = anguloSimulado.toFixed(1);

    if (angleDeviation) {
      angleDeviation.textContent = (variacion >= 0 ? "+" : "") + variacion.toFixed(1) + "°";
    }

    const dentroDeTolerancia = anguloSimulado >= tolMinActual && anguloSimulado <= tolMaxActual;

    if (dentroDeTolerancia) {
      if (measuredAngleEl) measuredAngleEl.className = "fs-2 fw-bold text-success";
      if (toleranceBadge) {
        toleranceBadge.className = "badge bg-success mb-1";
        toleranceBadge.textContent = "Aprobado — Auto-Acelerando";
      }
    } else {
      if (measuredAngleEl) measuredAngleEl.className = "fs-2 fw-bold text-warning";
      if (toleranceBadge) {
        toleranceBadge.className = "badge bg-warning text-dark mb-1";
        toleranceBadge.textContent = "Rechazado / Desvío (Línea Continua)";
      }
    }
  }

  simularCapturaAltaVelocidad();
  setInterval(simularCapturaAltaVelocidad, 4000);

  // 4. Envío asíncrono al iniciar batch (avanza al siguiente batch automáticamente)
  if (formIniciarBatch) {
    formIniciarBatch.addEventListener("submit", async function (e) {
      e.preventDefault();
      const formData = new FormData(formIniciarBatch);

      try {
        const resp = await fetch(formIniciarBatch.action, {
          method: "POST",
          headers: { "X-Requested-With": "XMLHttpRequest" },
          body: formData
        });
        const data = await resp.json();

        if (resp.ok && data.status === "success") {
          ultimoRegistroId = data.registro_id;
          contadorBatch++;
          actualizarMetricasReceta();
          mostrarAlertaUI(data.mensaje, data.estado === "Aprobado" ? "success" : "warning");
        } else {
          mostrarAlertaUI(data.mensaje || "Error al iniciar batch.", "danger");
        }
      } catch (err) {
        mostrarAlertaUI("Error de conexión con el servidor.", "danger");
      }
    });
  }

  // 5. Guardar Observación en BD
  const btnGuardarObs = document.getElementById("btn-guardar");
  const inputObs = document.getElementById("input-observacion");

  if (btnGuardarObs && inputObs) {
    btnGuardarObs.addEventListener("click", async function (e) {
      e.preventDefault();
      const texto = inputObs.value.trim();
      if (!texto) {
        mostrarAlertaUI("Escribe una observación antes de guardar.", "warning");
        return;
      }

      const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || "";
      const anguloActual = hiddenAngulo ? hiddenAngulo.value : "180.0";

      try {
        const resp = await fetch("/api/operador/guardar_observacion", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
          },
          body: JSON.stringify({
            observacion: texto,
            registro_id: ultimoRegistroId,
            angulo_actual: anguloActual
          })
        });
        const data = await resp.json();

        if (resp.ok && data.status === "success") {
          inputObs.value = "";
          mostrarAlertaUI(data.mensaje, "success");
        } else {
          mostrarAlertaUI(data.mensaje || "No se pudo guardar la observación.", "danger");
        }
      } catch (err) {
        mostrarAlertaUI("Error de red al guardar observación.", "danger");
      }
    });
  }

  function mostrarAlertaUI(mensaje, tipo) {
    const contenedor = document.querySelector(".row.g-4")?.parentElement;
    if (!contenedor) return;

    const alertaExistente = document.getElementById("alerta-dinamica-aza");
    if (alertaExistente) alertaExistente.remove();

    const div = document.createElement("div");
    div.id = "alerta-dinamica-aza";
    div.className = `alert alert-${tipo} alert-dismissible fade show shadow-sm`;
    div.role = "alert";
    div.innerHTML = `
      <i class="fa-solid fa-circle-info me-2"></i> ${mensaje}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Cerrar"></button>
    `;
    contenedor.insertBefore(div, contenedor.firstChild);
  }
});