// SPDX-License-Identifier: Apache-2.0
// Testing Library unmounts after each test only with vitest's globals, which this project leaves off.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
