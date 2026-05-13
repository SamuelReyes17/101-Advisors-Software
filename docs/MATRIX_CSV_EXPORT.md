# Cómo exportar el CSV de Matrix al dashboard

**Tiempo: 3 minutos al día** (una sola vez cada mañana).

## El proceso en 4 pasos

### 1. Entrar a Matrix

Login en [sef.mlsmatrix.com](https://sef.mlsmatrix.com) con las credenciales del cliente.

### 2. Abrir tus Saved Searches

- Hover sobre **MY MATRIX** en el menú top → click **Auto Emails** (o **Saved Searches**).
- Vas a ver tus 3 saved searches:
  - 101 Advisors REO - Daily Alert
  - 101 Advisors Short Sale - Daily Alert
  - 101 Advisors Auction - Daily Alert

### 3. Correr cada saved search y exportar a CSV

Para cada una de las 3:

1. Click en el nombre de la saved search → click **"Results"** (link gris debajo del nombre).
2. Te lleva a la página de resultados con la lista de listings.
3. Arriba de la tabla, marcá la casilla del header (selecciona TODOS los listings de la página) — o seleccioná los que querés exportar.
4. Click el botón **"Actions"** (abajo a la izquierda en la barra azul) → **"Export"**.
5. En el dialog: seleccioná formato **"CSV"** → click **"Export"**.
6. Matrix descarga un archivo `.csv` a tu carpeta Downloads.
7. Renombralo para identificarlo, ej: `mls_reo_2026-05-13.csv`.

### 4. Subir al dashboard

1. Abrí tu dashboard: `https://101-advisors-software-*.streamlit.app`
2. Login con la password compartida.
3. En la **barra lateral izquierda**, vas a ver una sección **"📤 Subir leads de MLS"**.
4. Click "Browse files" o arrastrá el archivo CSV ahí.
5. El sistema procesa el CSV automáticamente — muestra un mensaje ✅ con la cantidad de leads cargados.
6. Click el botón **🔄 Refresh** arriba para ver los leads actualizados en la tabla.

¡Listo! El equipo de 101 Advisors puede entrar al dashboard y ver los leads del día.

## ¿Cuántos CSVs hay que subir?

Las 3 saved searches pueden subirse por separado o combinarse en un solo CSV. Si subís uno y después otro, el segundo **reemplaza** al primero. Para tener los 3 al mismo tiempo:

**Opción A — Subir los 3 CSVs combinados** (más práctico):
1. Abrí los 3 CSVs en Excel/Numbers.
2. Copy/paste las filas del 2do y 3er CSV al final del primero (mantené solo 1 fila de headers).
3. Save as `mls_combined_2026-05-13.csv`.
4. Subí ese único archivo al dashboard.

**Opción B — Subir uno cada día rotando**:
- Lunes/Jueves: REO
- Martes/Viernes: Short Sale
- Miércoles/Sábado: Auction

Funciona pero pierde cobertura simultánea.

## Si Matrix no tiene botón "Export"

Algunos Matrix tienen el botón en distinto lugar:
- Barra de **"Actions"** abajo
- Menú **"Send/Export"** arriba a la derecha
- Click derecho sobre la tabla → "Export selection"

Si no lo encontrás, sacá screenshot y mando el lugar exacto.

## Frecuencia recomendada

- **Diario** — mejor, el cliente ve leads frescos cada mañana.
- **Cada 2 días** — aceptable si tenés muchos compromisos.
- **Semanal** — mínimo aceptable, pero perdés la ventaja de "llegar primero".

## Próximos pasos (semanas siguientes)

Una vez validado que el flujo CSV funciona, vamos a:

1. **Automatizar el upload** — vos solo descargás de Matrix, el dashboard absorbe el CSV de una carpeta de Google Drive sin que tengas que loguearte.
2. **Activar API formal (Trestle/Bridge)** — el broker firma el display agreement, esperamos 1-3 semanas, después acceso programático directo sin necesidad de CSV.

Con cualquiera de las dos mejoras, llegamos a "0 minutos por día" del flujo actual.
