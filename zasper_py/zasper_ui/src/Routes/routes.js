import {
  BrowserRouter,
  Route,
  Routes,
} from "react-router-dom";
import React from 'react';
import Lab from "../lab/Lab";

const routes = [
  {
    path: "/",
    component: Lab,
    protected: false
  },
];

export default function RouteConfigExample() {
  return (
    <BrowserRouter>
      <Routes>
        {routes.map((route, i) => {
          return <Route key={i} path={route.path} element={<route.component />} />;
        })}
      </Routes>
    </BrowserRouter>
  );
}
