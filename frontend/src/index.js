import "@/publicPath";
import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import BookingProduct from "@/pages/BookingProduct";
import { installErrorReporting } from "@/lib/errorReporting";

installErrorReporting();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    {(window.location.pathname.startsWith("/booking-app") || window.location.pathname.startsWith("/book/v/") || window.location.hostname === "booking.nuapos.com.au") ? <BookingProduct /> : <App />}
  </React.StrictMode>,
);
