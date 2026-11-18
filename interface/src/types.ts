// Types partagés avec l'API du Core (core/jarvis2/api.py).

export interface InfoModele {
  id: string;
  nom: string;
  defaut: boolean;
}

export interface InfoMoteur {
  id: string;
  nom: string;
  externe: boolean;
  disponible: boolean;
  detail: string;
  modeles: InfoModele[];
  efforts: string[];
  effort_defaut: string | null;
}

export interface ResumeConversation {
  id: string;
  titre: string;
  titre_source: string;
  epinglee: boolean;
  archivee: boolean;
  cree_le: string;
  maj_le: string;
  nb_messages: number;
}

export interface Etat {
  version: string;
  moteur_defaut: string;
  moteurs: InfoMoteur[];
  conversations: ResumeConversation[];
}

export interface MetaMessage {
  moteur?: string;
  modele?: string | null;
  effort?: string;
  cout_usd?: number;
  jetons_entree?: number | null;
  jetons_sortie?: number | null;
  source_auth?: string;
  interrompu?: boolean;
  erreur?: string;
}

export interface MessageStocke {
  id: number;
  role: "utilisateur" | "jarvis";
  contenu: string;
  horodatage: string;
  meta: MetaMessage;
}

export interface DetailConversation {
  conversation: ResumeConversation;
  messages: MessageStocke[];
}

export interface DemandeDialogue {
  message: string;
  conversation_id?: string;
  moteur?: string;
  modele?: string;
  effort?: string;
}

export type EvenementDialogue =
  | { type: "debut"; donnees: { conversation_id: string; titre: string; moteur: string; modele: string | null } }
  | { type: "delta"; donnees: { texte: string } }
  | { type: "fin"; donnees: MetaMessage & { message_id: number; texte: string } }
  | { type: "erreur"; donnees: { message: string; conversation_id?: string } };
