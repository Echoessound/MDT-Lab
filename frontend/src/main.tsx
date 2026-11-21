import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, HashRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import './styles.css';
import './console/console.css';

// A desktop window can load /?shell=desktop#/... from the same loopback service.
const Router = new URLSearchParams(window.location.search).get('shell') === 'desktop' ? HashRouter : BrowserRouter;

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 1000, refetchOnWindowFocus: false } } });
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><QueryClientProvider client={queryClient}><Router><App /></Router></QueryClientProvider></React.StrictMode>,
);
