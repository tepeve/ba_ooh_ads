# Resumen de Debugging - Dashboard BA OOH Ads

Fecha: 24 de Enero, 2026
Estado: En Progreso

---

### 📋 Resumen de Intentos (Sesión 1: ETL y SQL)

Desde el punto de restauración, se realizaron acciones para corregir la visualización del mapa:

1.  **Validación de Datos (ETL):** Se confirmó la integridad de `needs_geocoding` y tipos numéricos en lat/long.
2.  **Diagnóstico SQL (DuckDB):** Se ajustaron las comparaciones booleanas y strings en los filtros.
3.  **Manejo de UI:** Se convirtieron valores booleanos a strings explícitos en los selectores.
4.  **Corrección de Runtime Errors:** Se solucionó el `ValueError: too many values to unpack` agregando `*_`.

---

### 📋 Resumen de Intentos (Sesión 2: Renderizado y Estabilidad)

Se realizó una refactorización profunda de la lógica de renderizado del mapa (`ipyleaflet`) para solucionar problemas de usabilidad. A continuación, la evolución de los síntomas y soluciones:

**Fase 1: El Bug de Reinicio (Estado Inicial)**
* **Síntoma:** Al filtrar, el mapa se reiniciaba automáticamente a las coordenadas `(0,0)` en el Océano Atlántico.
* **Observación Clave:** Los marcadores (CircleMarkers) **SÍ se renderizaban correctamente**, pero el usuario debía desplazarse manualmente hasta el Golfo de Guinea (donde aparecían los puntos) o buscar Buenos Aires para ver si estaban allí.
* **Causa:** El uso de `@render_widget` recreaba la instancia del mapa (`L.Map`) en cada actualización, perdiendo el estado del viewport.

**Fase 2: El Bug de la Pantalla Gris (Intento de Mutación 1)**
* **Acción:** Se intentó pasar a un modelo de mutación usando `@reactive.Effect` y limpiando el mapa con `map_widget.clear_layers()` antes de agregar nuevos puntos.
* **Síntoma:** Al aplicar un filtro, el mapa desaparecía completamente, dejando un lienzo **gris uniforme** sin posibilidad de navegar ni ver tiles (mapa base).
* **Causa:** La función `clear_layers()` ejecutada sobre el objeto mapa elimina **todas** las capas, incluyendo la capa base de azulejos (CartoDB/OSM), rompiendo la visualización.

**Fase 3: Estabilización (Estado Actual)**
* **Acción:** Se implementó un `LayerGroup` dedicado exclusivamente para los marcadores y se instanció el mapa una única vez (fuera de la lógica reactiva).
* **Resultado:** El mapa ahora es estable, mantiene el centro en Buenos Aires y no se pone gris. Sin embargo, esto reveló el bug actual (ver abajo).

---

### 🐞 Registro de Bug (QA Report) - RESUELTO ✅

**ID:** BUG-DASH-002 (Estado: **CERRADO**)
**Título:** Marcadores de datos invisibles a pesar de mapa estable.
**Fecha de Resolución:** 24 de Enero, 2026

**Descripción del Problema:**
Habiendo superado los problemas de reinicio de vista (Fase 1) y desaparición del mapa base (Fase 2), el componente `ipyleaflet` se comportaba de manera estable pero **los puntos dinámicos del dataset no se visualizaban en el mapa**.

**Síntomas Observados:**
1.  El mapa base cargaba correctamente centrado en CABA.
2.  Marcadores estáticos de prueba (hardcodeados) **SÍ se veían**.
3.  Marcadores dinámicos del dataset **NO se veían**, confirmado en logs que se creaban correctamente (48 marcadores).
4.  Auditoría de coordenadas confirmó que los valores de lat/long eran correctos (-34.6°, -58.4°) y dentro del rango esperado para CABA.

**Causa Raíz Identificada:**
Bug de **sincronización entre el kernel de Python y el widget de JavaScript** en `ipyleaflet` dentro del contexto reactivo de Shiny for Python. Los marcadores se creaban correctamente en el backend pero no se renderizaban en el DOM del navegador.

**Hipótesis Descartadas mediante Testing Sistemático:**
* ~~**Fallo de Librería/Entorno:**~~ Descartado mediante prueba de marcador estático ("Testigo").
* ~~**Saturación de Renderizado:**~~ Descartado al reducir el dataset a 10 filas.
* ~~**Borrado de Tiles:**~~ Descartado al usar `LayerGroup` en lugar de `clear_layers()`.
* ~~**Proyección/Coordenadas:**~~ Descartado mediante logs que confirmaron valores WGS84 válidos.
* ~~**Serialización de Datos:**~~ Descartado al verificar tipos de datos y casteo explícito a float.

**Solución Implementada:**
**Migración de `ipyleaflet` a `folium`** para el renderizado del mapa:

1.  **Dependencia agregada:** `folium>=0.15.0` al proyecto.
2.  **Cambio de renderizado:** De `@render_widget` (widgets interactivos) a `@render.ui` (HTML estático).
3.  **Método de visualización:** Folium genera el mapa como HTML embebido (`m._repr_html_()`) que se inyecta directamente en el DOM.
4.  **MarkerCluster:** Implementado de forma nativa mediante `folium.plugins.MarkerCluster` para agrupación automática.
5.  **Popups HTML:** Diseñados con estilos personalizados para mostrar información completa de cada anuncio.

**Resultado:**
✅ Los marcadores ahora se visualizan correctamente en el mapa.
✅ El clustering funciona de manera fluida con datasets de 50+ puntos.
✅ La reactividad de filtros es instantánea sin pérdida de estado del viewport.
✅ No hay dependencia de sincronización de widgets JavaScript.

**Lecciones Aprendidas:**
* `ipyleaflet` tiene limitaciones conocidas en contextos reactivos de Shiny (confirmado en documentación de shinywidgets).
* `folium` es más confiable para dashboards en producción al generar HTML estático compatible con cualquier framework.
* La auditoría sistemática de coordenadas mediante logs fue crucial para descartar hipótesis erróneas.

---

### 📚 Archivo del Proceso de Debugging (Para Referencia)

**Fase 1: El Bug de Reinicio**
* **Síntoma:** Mapa se reiniciaba a (0,0) al filtrar.
* **Solución:** Instanciar mapa una sola vez fuera de `@render_widget`.

**Fase 2: El Bug de la Pantalla Gris**
* **Síntoma:** Al filtrar, el mapa desaparecía (pantalla gris).
* **Solución:** Usar `LayerGroup` para marcadores en lugar de `clear_layers()` sobre el mapa base.

**Fase 3: El Bug de Marcadores Invisibles (ACTUAL)**
* **Síntoma:** Marcadores creados pero no visibles en el DOM.
* **Solución:** Migración completa a Folium.

**Workflow de Debugging Aplicado:**
1.  ✅ Crear "marcadores testigo" hardcodeados → Confirmó que el framework funcionaba.
2.  ✅ Auditoría de logs de coordenadas crudas → Descartó problemas de proyección.
3.  ✅ Reducción de dataset a 10 registros → Descartó saturación de memoria.
4.  ✅ Prueba con diferentes métodos de limpieza (`clear_layers`, `markers = []`, `add_layer`) → Confirmó bug de sincronización.
5.  ✅ Migración a tecnología alternativa (Folium) → Resolvió el problema definitivamente.