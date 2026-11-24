/**
 * Aceros AZA
 * Módulo: Reportes de Administración
 *
 * Gestiona la visualización de filtros según
 * el tipo de reporte seleccionado.
 */

document.addEventListener("DOMContentLoaded", () => {

    const selectorReporte = document.getElementById("tipo-reporte");

    if (!selectorReporte) {
        return;
    }

    /**
     * Muestra u oculta un conjunto de filtros.
     * Deshabilita los campos ocultos para evitar
     * enviarlos innecesariamente al servidor.
     */
    function configurarFiltros(selector, mostrar) {
        const elementos = document.querySelectorAll(selector);

        elementos.forEach(elemento => {
            elemento.classList.toggle("d-none", !mostrar);

            const campos = elemento.querySelectorAll(
                "input, select, textarea"
            );

            campos.forEach(campo => {
                campo.disabled = !mostrar;
            });
        });
    }

    /**
     * Identifica la categoría del reporte
     * seleccionado y actualiza los filtros.
     */
    function actualizarFiltros() {

        const opcionSeleccionada =
            selectorReporte.options[selectorReporte.selectedIndex];

        const categoria =
            opcionSeleccionada?.dataset.category || "";

        const esAuditoria =
            categoria === "auditoria" ||
            categoria === "bloqueados";

        const esHistorialAuditoria =
            categoria === "auditoria";

        // Filtros de producción y calidad
        configurarFiltros(
            ".filtro-produccion",
            !esAuditoria
        );

        // Filtro de usuario afectado
        configurarFiltros(
            ".filtro-auditoria",
            esAuditoria
        );

        // Filtro específico de eventos de auditoría
        configurarFiltros(
            ".filtro-evento",
            esHistorialAuditoria
        );
    }

    // Cambio de tipo de reporte
    selectorReporte.addEventListener(
        "change",
        actualizarFiltros
    );

    // Configuración inicial
    actualizarFiltros();

});