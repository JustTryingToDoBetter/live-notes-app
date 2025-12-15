<?php
 
use Illuminate\Support\Facades\Route;
use App\Http\Controllers\NoteController;

Route::get('/notes', [NoteController::class, 'index']);
Route::post('/notes', [NoteController::class, 'store']);