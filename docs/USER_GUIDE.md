# 101 Advisors · Lead Generation Platform
## Manual del Usuario

Bienvenidos a la nueva herramienta automatizada de generación de leads para distressed properties. Esta guía les explica cómo usarla en 5 minutos.

---

## 🔗 Acceso

**URL:** `https://101-advisors-software-[código].streamlit.app`

**Password:** se las comparte Samuel por canal privado (NO compartir con personas fuera del equipo).

**Compatibilidad:** funciona en cualquier browser (Chrome, Safari, Firefox, Edge) desde computadora, celular, o tablet.

---

## 🎯 Qué hace el sistema

Cada mañana a las 6:00 AM ET, el sistema:

1. Consulta automáticamente SEF MLS Matrix y otras fuentes.
2. Filtra propiedades según los criterios de 101 Advisors:
   - Single Family, Multi-Family, Duplex, Triplex, Fourplex
   - Miami-Dade, Broward, Palm Beach
   - REO, Short Sale, Foreclosure Auction
3. Enriquece cada propiedad con datos del Property Appraiser (owner, año, lot size, etc).
4. Busca el teléfono y email del dueño automáticamente.
5. Publica los leads nuevos en este dashboard.

**Ustedes solo entran al dashboard cada mañana y empiezan a llamar.** No hay que configurar nada.

---

## 📊 Cómo usar el dashboard

### Pantalla principal

Al ingresar verán:

- **Header con la fecha** de la última actualización.
- **5 KPIs arriba**: leads nuevos hoy, pendientes, contactados esta semana, llamadas agendadas, equity promedio.
- **Filtros en la barra lateral izquierda**: county, categoría, tipo de propiedad, estado.
- **Tabla central**: lista de leads filtrados.

### Filtros (sidebar izquierda)

Usalos para enfocar la búsqueda:

- **County**: Miami-Dade / Broward / Palm Beach (marcá los que te interesan).
- **Categoría**: Foreclosure, Probate, Lis Pendens, Tax Delinquent, Liens.
- **Property type**: Single Family, Multi-Family, Duplex, Triplex, Fourplex.
- **Status**: New (no contactado), Pending, Contacted, Scheduled, Closed.
- **Min equity**: solo mostrar propiedades con equity arriba de cierto valor.

### Tabs (arriba de la tabla)

- **📍 Today** — leads NUEVOS del día (recién aparecieron por primera vez).
- **⏳ Pipeline** — todos los leads activos sin cerrar todavía.
- **✅ History** — leads ya contactados o cerrados.
- **📊 Stats** — gráficos de distribución por categoría, county, status.

### Click en una propiedad

Al hacer click en una row, se abre un panel de detalle abajo con:

- **Property**: dirección completa, tipo, beds/baths, units.
- **Owner**: nombre, teléfono, email.
- **Lender / Bank**: nombre del banco, contacto, dirección.
- **Finanzas**: outstanding debt, taxes 2024 / 2025, equity.

### Acciones disponibles

- **📥 Export CSV** — bajar la lista filtrada a Excel.
- **✅ Mark contacted** — marcar lead como contactado (se mueve a History).
- **👤 Assign agent** — asignar lead a un agente específico.

---

## 🔄 Refresh automático

El sistema se actualiza solo cada mañana a las **6:00 AM ET**. No tienen que apretar nada.

Si necesitan forzar un refresh manualmente, hay un botón "🔄 Refresh" arriba a la derecha.

---

## 🔒 Seguridad

- **No compartan la URL ni la password** con personas fuera del equipo.
- Si sospechan que la password se filtró, contacten a Samuel inmediatamente para rotarla.
- La sesión se cierra sola al cerrar el browser (no queda logueada en computadoras compartidas).

---

## ⚙️ Modos del sistema

El header muestra un badge:

- **🟢 Live data** = sistema activo con leads reales del MLS.
- **🟡 Preview mode** = están viendo datos de demostración. Los leads reales empiezan a fluir una vez completada la integración (durante la primera semana).

---

## 🆘 Soporte

**Mantenimiento técnico**: Samuel Reyes (`samuelreyesespinal02@gmail.com`)

**Tiempo de respuesta**: < 24 horas en horario laboral.

**Problemas comunes**:

| Síntoma | Solución |
|---|---|
| No carga el dashboard | Refrescá el browser (Cmd+R / Ctrl+R). Si persiste, contactar a Samuel. |
| Password no funciona | Verificar que sea exactamente como te la pasaron (case-sensitive). Contactar a Samuel si sigue sin entrar. |
| No aparecen leads nuevos | Verificar si están en modo Preview (banner amarillo arriba). Si están en Live, contactar a Samuel — puede ser un día sin nuevos matches. |
| Quiero cambiar los criterios de filtrado | Contactar a Samuel para ajustar el filtro del backend. |

---

## 📅 Roadmap (qué viene después)

**Esta semana**: integración SEF MLS Matrix completa → leads reales empiezan a fluir.

**Próximas semanas**: integración con Miami-Dade Clerk of Court (Foreclosure filings tempranos, Lis Pendens, Probate).

**A definir**: integración con CRM si lo necesitan (Follow Up Boss, HubSpot, etc.).

---

**¡Bienvenidos a la era automatizada de lead generation! 🚀**
