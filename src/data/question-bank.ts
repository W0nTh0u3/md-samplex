// Generated registry. Server use only; never import into client components.
import "server-only";
import { questions as v0 } from "./versions/bank-4cc48d81759145d0";
import { questions as v1 } from "./versions/bank-6d472680f42e1c0a";
import { questions as v2 } from "./versions/bank-f118f4a5cf4859fe";
export const BANK_VERSION = "bank-4cc48d81759145d0";
export const BANKS = { "bank-4cc48d81759145d0": v0, "bank-6d472680f42e1c0a": v1, "bank-f118f4a5cf4859fe": v2 };
export const questionBank = BANKS[BANK_VERSION];
