// Cloudflare Pages Function: every request to /api/... on haultimes.com lands here.
// The logic lives in api_lib/market.js so it can be tested outside Cloudflare.
import { handle } from "../../api_lib/market.js";

export async function onRequest(context) {
  try {
    return await handle(context.request, context.env);
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: "Something went wrong. Please try again." }), {
      status: 500, headers: { "content-type": "application/json" },
    });
  }
}
