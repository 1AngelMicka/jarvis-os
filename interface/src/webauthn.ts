// Clés d'accès (WebAuthn) : conversion entre les options JSON du Core (base64url) et l'API du navigateur.

type Json = Record<string, unknown>;

export function base64urlVersOctets(texte: string): ArrayBuffer {
  const base64 = texte.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(texte.length / 4) * 4, "=");
  const binaire = atob(base64);
  const octets = new Uint8Array(binaire.length);
  for (let i = 0; i < binaire.length; i++) octets[i] = binaire.charCodeAt(i);
  return octets.buffer;
}

export function octetsVersBase64url(tampon: ArrayBuffer | null): string | null {
  if (!tampon) return null;
  let binaire = "";
  for (const o of new Uint8Array(tampon)) binaire += String.fromCharCode(o);
  return btoa(binaire).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function clesDisponibles(): boolean {
  return typeof window.PublicKeyCredential === "function" && window.isSecureContext;
}

function descripteurs(liste: unknown): PublicKeyCredentialDescriptor[] {
  return Array.isArray(liste)
    ? liste.map((d: Json) => ({ type: "public-key" as const, id: base64urlVersOctets(String(d.id)) }))
    : [];
}

export async function creerCle(options: Json): Promise<Json> {
  const user = options.user as Json;
  const publicKey: PublicKeyCredentialCreationOptions = {
    challenge: base64urlVersOctets(String(options.challenge)),
    rp: options.rp as PublicKeyCredentialRpEntity,
    user: { id: base64urlVersOctets(String(user.id)), name: String(user.name), displayName: String(user.displayName) },
    pubKeyCredParams: options.pubKeyCredParams as PublicKeyCredentialParameters[],
    timeout: Number(options.timeout),
    excludeCredentials: descripteurs(options.excludeCredentials),
    authenticatorSelection: options.authenticatorSelection as AuthenticatorSelectionCriteria,
    attestation: "none",
  };
  const cle = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!cle) throw new Error("Création de la clé d'accès annulée.");
  const r = cle.response as AuthenticatorAttestationResponse;
  return {
    id: cle.id,
    rawId: octetsVersBase64url(cle.rawId),
    type: cle.type,
    response: {
      clientDataJSON: octetsVersBase64url(r.clientDataJSON),
      attestationObject: octetsVersBase64url(r.attestationObject),
      transports: typeof r.getTransports === "function" ? r.getTransports() : [],
    },
  };
}

export async function signerDefi(options: Json): Promise<Json> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    challenge: base64urlVersOctets(String(options.challenge)),
    rpId: String(options.rpId),
    timeout: Number(options.timeout),
    allowCredentials: descripteurs(options.allowCredentials),
    userVerification: "required",
  };
  const cle = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!cle) throw new Error("Approbation annulée.");
  const r = cle.response as AuthenticatorAssertionResponse;
  return {
    id: cle.id,
    rawId: octetsVersBase64url(cle.rawId),
    type: cle.type,
    response: {
      clientDataJSON: octetsVersBase64url(r.clientDataJSON),
      authenticatorData: octetsVersBase64url(r.authenticatorData),
      signature: octetsVersBase64url(r.signature),
      userHandle: octetsVersBase64url(r.userHandle),
    },
  };
}
