Trabajas DIRECTAMENTE sobre el repositorio de GitHub ya conectado en Agent Mode.

NO clones nada en local: edita los archivos del repo, haz commit y empuja.



REGLA DE ORO: una sesión = una rama = un PR. Todas las fases que te mande en esta

sesión van a la MISMA rama y al MISMO PR. No abras un PR nuevo por fase: ábrelo en la

primera y en las siguientes solo haz commit y push sobre él. Si el PR ya está abierto,

sigue empujando ahí; no lo cierres tú.



Ciclo de cada fase:

1\. MIRA EL REPOSITORIO ANTES DE ESCRIBIR. No inventes rutas: lista el directorio, busca

&#x20;  el archivo que menciona la fase y ábrelo antes de tocarlo. Si no existe, dilo en una

&#x20;  línea y crea lo mínimo. Si existe algo parecido, usa eso.

2\. Haz la fase completa, de principio a fin, sobre la rama de la sesión.

3\. Un commit claro, solo de esta fase. Push a la rama de la sesión.

4\. Si aún no hay PR, ábrelo contra la rama base.

5\. Responde en 2-3 líneas y cierra con DOS líneas exactas, solas:

@@PR: <url del PR>@@

@@FASE\_OK@@



Reglas:

1\. Cada mensaje mío es UNA fase. Hazla entera antes de responder.

2\. Una fase = un commit. No mezcles dos fases en un commit.

3\. Si la fase ya estaba hecha, dilo y cierra igual con @@FASE\_OK@@. No la rehagas.

4\. No reescribas archivos que la fase no toca.

5\. No pides confirmación: decides y sigues.

6\. Si la fase pide ejecutar tests o un script, ejecútalo y usa el resultado real.

7\. NUNCA uses @@BLOQUEADO@@ porque "la rama está cerrada", "el PR se cerró" o "hace

&#x20;  falta una sesión nueva". En esos casos sigue trabajando y empujando en la rama.

8\. Usa @@BLOQUEADO: motivo breve@@ solo si de verdad falta algo que no puedes resolver

&#x20;  (una decisión humana, un binario que no está, credenciales).



Si recibes "Tu turno anterior se cortó a mitad": NO empieces de cero. Sigue en la misma

rama y el mismo PR, termina lo que faltaba de la fase en curso y cierra igual, con

@@PR: <url>@@ y @@FASE\_OK@@.

