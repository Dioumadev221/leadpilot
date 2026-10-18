# Mettre LeadPilot en ligne (gratuit)

Hébergement : **Vercel** (le site et l'API) + **Neon** (la base de données). Les deux sont gratuits, sans carte bancaire, et le site ne s'endort pas.

## Étape 1 : la base de données (Neon)

1. Va sur https://neon.tech et connecte-toi avec GitHub.
2. Clique **New Project**. Nom : `leadpilot`. Région : Europe (Frankfurt), la même que le site.
3. Sur la page du projet, clique **Connect**.
4. Coche **Connection pooling** (important).
5. Copie la ligne qui commence par `postgresql://...`. C'est ton `DATABASE_URL`. Garde-la de côté.

## Étape 2 : le site (Vercel)

1. Va sur https://vercel.com et connecte-toi avec GitHub.
2. Clique **Add New → Project**, choisis le dépôt `leadpilot`, clique **Import**.
3. Ouvre **Environment Variables** et ajoute :

| Nom | Valeur |
|---|---|
| `DATABASE_URL` | la ligne copiée sur Neon |
| `DEMO_MODE` | `true` |
| `LLM_PROVIDER` | `none` |
| `CRON_SECRET` | une suite de lettres et chiffres au hasard (20 caractères) |
| `CONTACT_URL` | le lien de ton profil Upwork |

4. Clique **Deploy** et attends la fin (1 à 2 minutes).
5. Vercel te donne une adresse du type `https://leadpilot-xxxx.vercel.app`.

## Étape 3 : le lien de partage

1. Dans Vercel → **Settings → Environment Variables**, ajoute `PUBLIC_URL` = ton adresse Vercel.
2. **Deployments** → les trois points du dernier déploiement → **Redeploy**.

Ton site est en ligne : `/` est la page produit, `/app` est l'application.

## Plus tard (optionnel) : un vrai modèle d'IA gratuit

Crée une clé sur https://console.groq.com, puis ajoute dans Vercel :
`LLM_PROVIDER=openai`, `OPENAI_BASE_URL=https://api.groq.com/openai/v1`, `OPENAI_API_KEY=ta clé`, `LLM_MODEL=llama-3.3-70b-versatile`. Redeploy.
