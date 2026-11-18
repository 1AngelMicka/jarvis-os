import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: { project: ["./tsconfig.json"], tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // Règle du design : jamais de HTML brut injecté depuis des données.
      "no-restricted-properties": ["error",
        { property: "innerHTML", message: "Interdit : construire le DOM avec React (DESIGN.md, règle 2)." },
        { property: "outerHTML", message: "Interdit : construire le DOM avec React (DESIGN.md, règle 2)." }],
      "no-restricted-syntax": ["error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "Interdit (DESIGN.md, règle 2)." }],
    },
  },
  { files: ["eslint.config.js"], extends: [tseslint.configs.disableTypeChecked] },
);
