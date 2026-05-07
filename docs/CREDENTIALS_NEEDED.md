# Credenciales que necesitamos del cliente (101 Advisors)

Este documento lista exactamente qué información hay que pedirle al cliente para poder integrar la plataforma comercial que ellos ya pagan, sin esperar de más por respuestas.

## 1. Nombre exacto de la plataforma

¿Qué servicio están pagando actualmente para distressed property leads? Las más comunes son:

- PropStream / PropStream Intelligence
- BatchLeads / BatchData
- Foreclosure.com
- Auction.com
- DealMachine
- Privy
- REIPro
- ATTOM Data
- Goliath Data
- (otra)

**Pregunta concreta al cliente**:
> "¿Cuál plataforma usan ahora para encontrar leads de distressed properties? Necesito el nombre exacto y el plan que tienen (ej: PropStream Pro, BatchLeads Premium)."

## 2. Acceso para integración

Dependiendo de la plataforma, necesitamos UNA de estas tres cosas:

### Opción A — API key (lo ideal)

> "¿Su plataforma tiene una API? Si sí, necesito que generen una API key desde el panel de admin y me la compartan. Suele estar en Settings → Developer → API Keys."

Plataformas que tienen API documentada:
- BatchData / BatchLeads
- ATTOM Data
- PropStream (planes Pro+)
- Realeflow

### Opción B — Login compartido (si no hay API)

> "Si la plataforma no tiene API, necesito un usuario dedicado para automatización (puede ser un seat extra o el mismo que ustedes usan). Compartir username + password de manera segura — ideal en 1Password compartido o LastPass shared vault, NO por email plain text."

### Opción C — OAuth / SSO

Algunas plataformas permiten generar tokens con scopes limitados. Si la suya tiene esa opción, mejor.

## 3. Información sobre filtros que ya usan

Para replicar exactamente lo que el equipo ve hoy en su búsqueda manual, necesito:

> "¿Pueden mandarme un screenshot de los filtros que actualmente aplican en la plataforma cuando buscan leads? Quiero replicar exactamente esos criterios para que el sistema automatizado entregue lo mismo (o más, dependiendo de las capacidades del API)."

Específicamente:
- Categorías activas (foreclosure, probate, etc.)
- Counties
- Property types incluidos/excluidos
- Rangos de equity / value / días en mercado
- Cualquier filtro avanzado que usen

## 4. Volumen actual

Para dimensionar caps y costo:

> "¿Cuántos leads les muestra la plataforma hoy en una búsqueda típica? ¿Es una búsqueda diaria o cada cuánto? Esto define cuántos calls a la API hace nuestro sistema y el costo asociado si la plataforma cobra por uso."

## 5. (Opcional) Si tienen acceso al MLS

Si 101 Advisors es agencia de real estate licenciada, además de la plataforma probablemente tengan MLS access. Eso es independiente y muy útil.

> "¿Su broker tiene acceso a Bridge Interactive o MLS Grid? Si sí, podemos integrar el feed RESO Web API en paralelo a la plataforma — esto agrega flags de Bank-Owned (REO), Short Sale, Pre-Foreclosure que vienen directo de la MLS."

(Ver `101 Advisors - Plataforma Lead Generation v2.docx` Sección 5 para detalles MLS.)

---

## Cuando el cliente responda

Mandame por chat:

1. **Nombre exacto de la plataforma** (ej: "PropStream Standard").
2. **API key** O **login + password** (de manera segura — no en plain text en email; ideal usar 1Password compartido).
3. **Screenshots de los filtros actuales** que usan.
4. **Volumen estimado** de leads/día.
5. **(Opcional)** MLS provider y rol broker/agent.

Con eso puedo terminar la integración en 1-3 días según la plataforma.
