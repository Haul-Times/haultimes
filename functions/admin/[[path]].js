// Cloudflare Pages Function: haultimes.com/admin/... — the private admin panel (password protected).
import { handleAdmin } from "../../api_lib/admin.js";
import { PAGE } from "../../api_lib/admin_page.js";

export async function onRequest(context) {
  try {
    return await handleAdmin(context.request, context.env, PAGE);
  } catch (e) {
    return new Response("Admin error. Please try again.", { status: 500, headers: { "x-robots-tag": "noindex" } });
  }
}
